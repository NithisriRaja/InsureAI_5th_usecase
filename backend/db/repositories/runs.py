"""Run queue persistence.

Race guards (see ``backend.db.store`` on why a check-then-write without ``await`` is atomic):
- ``enqueue``: the store's unique rule (one queued/running run per subject) is the real guard;
  a losing concurrent insert returns the existing active run instead.
- ``claim_next``: picks the oldest queued run and marks it running in one step, so two workers
  can never claim the same run.
- ``finish``/``heartbeat``: only the worker that claimed the run may touch it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from backend.db.models import Run
from backend.db.store import DbSession, IntegrityError
from backend.enums import ACTIVE_RUN_STATUSES, RunStatus
from backend.utils.clock import utcnow
from backend.utils.ids import new_id


def _newest_first(runs: list[Run]) -> list[Run]:
    return sorted(runs, key=lambda r: (r.created_at, r.id), reverse=True)


async def get(s: DbSession, run_id: str) -> Run | None:
    return await s.get(Run, run_id)


async def active_for(s: DbSession, subject_type: str, subject_id: str) -> Run | None:
    return next(
        (
            r
            for r in s.all(Run)
            if r.subject_type == subject_type
            and r.subject_id == subject_id
            and r.status in ACTIVE_RUN_STATUSES
        ),
        None,
    )


async def latest_for(s: DbSession, subject_type: str, subject_id: str) -> Run | None:
    runs = s.where(Run, lambda r: r.subject_type == subject_type and r.subject_id == subject_id)
    return _newest_first(runs)[0] if runs else None


async def enqueue(
    s: DbSession,
    *,
    use_case: str,
    subject_type: str,
    subject_id: str,
    cycle_key: str,
    max_attempts: int,
    batch_id: str | None = None,
    requested_by: str | None = None,
) -> tuple[Run, bool]:
    """Returns ``(run, created)``. ``created=False`` means an active run already existed."""
    existing = await active_for(s, subject_type, subject_id)
    if existing:
        return existing, False
    run = Run(
        id=new_id("run"),
        batch_id=batch_id,
        use_case=use_case,
        subject_type=subject_type,
        subject_id=subject_id,
        cycle_key=cycle_key,
        status=RunStatus.QUEUED.value,
        max_attempts=max_attempts,
        requested_by=requested_by,
    )
    s.add(run)
    return run, True


async def claim_next(s: DbSession, worker_id: str) -> Run | None:
    queued = s.where(Run, lambda r: r.status == RunStatus.QUEUED)
    if not queued:
        return None
    run = min(queued, key=lambda r: (r.created_at, r.id))
    now = utcnow()
    run.status = RunStatus.RUNNING.value
    run.claimed_by = worker_id
    run.started_at = now
    run.heartbeat_at = now
    run.attempts += 1
    return run


def _owned(run: Run | None, worker_id: str) -> bool:
    return run is not None and run.claimed_by == worker_id and run.status == RunStatus.RUNNING


async def heartbeat(s: DbSession, run_id: str, worker_id: str) -> bool:
    run = await s.get(Run, run_id)
    if not _owned(run, worker_id):
        return False
    run.heartbeat_at = utcnow()
    return True


async def finish(
    s: DbSession,
    run_id: str,
    worker_id: str,
    *,
    status: RunStatus,
    result: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> bool:
    run = await s.get(Run, run_id)
    if not _owned(run, worker_id):
        return False
    run.status = status.value
    run.result = result or {}
    run.error_code = error_code
    run.error_message = (error_message or "")[:2000] or None
    run.finished_at = utcnow()
    return True


async def recover_stale(
    s: DbSession, *, instance_prefix: str, stale_before: datetime
) -> tuple[list[str], list[str]]:
    """Requeue (or fail, if out of attempts) runs whose worker is gone: claimed by a previous
    process instance, or silent past the heartbeat deadline. Returns (requeued, failed)."""
    requeued: list[str] = []
    failed: list[str] = []
    for run in s.where(Run, lambda r: r.status == RunStatus.RUNNING):
        foreign = not (run.claimed_by or "").startswith(instance_prefix)
        silent = run.heartbeat_at is None or run.heartbeat_at < stale_before
        if not (foreign or silent):
            continue
        if run.attempts < run.max_attempts:
            run.status = RunStatus.QUEUED.value
            run.claimed_by = None
            run.error_code = "worker_lost"
            run.error_message = "Worker stopped before finishing; requeued."
            requeued.append(run.id)
        else:
            run.status = RunStatus.FAILED.value
            run.error_code = "worker_lost"
            run.error_message = f"Worker lost {run.attempts} times; giving up."
            run.finished_at = utcnow()
            failed.append(run.id)
    return requeued, failed


async def reset_for_retry(s: DbSession, run_id: str) -> Run | None:
    """Failed run -> queued again (keeps id so audit/LLM history stays together).

    Raises ``IntegrityError`` if another run for the same subject is already active."""
    run = await s.get(Run, run_id)
    if run is None or run.status != RunStatus.FAILED:
        return None
    if await active_for(s, run.subject_type, run.subject_id):
        raise IntegrityError(f"runs: active run exists for {run.subject_id}")
    run.status = RunStatus.QUEUED.value
    run.error_code = None
    run.error_message = None
    run.claimed_by = None
    run.finished_at = None
    run.attempts = 0
    run.created_at = utcnow()
    return run


async def list_(
    s: DbSession,
    *,
    status: str | None = None,
    batch_id: str | None = None,
    use_case: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Run], int]:
    rows = s.where(
        Run,
        lambda r: (not status or r.status == status)
        and (not use_case or r.use_case == use_case)
        and (not batch_id or r.batch_id == batch_id),
    )
    return _newest_first(rows)[offset : offset + limit], len(rows)


async def status_counts(s: DbSession, batch_id: str | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in s.all(Run):
        if not batch_id or r.batch_id == batch_id:
            out[r.status] = out.get(r.status, 0) + 1
    return out


def stale_cutoff(seconds: float) -> datetime:
    return utcnow() - timedelta(seconds=seconds)
