from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.api.deps import db_session, get_database, get_runner
from backend.api.errors import AppError, not_found
from backend.api.naming import subject_names
from backend.api.schemas.common import BatchOut, Page, RunOut
from backend.api.session_auth import optional_actor
from backend.db.models import Batch
from backend.db.repositories import audit as audit_repo
from backend.db.repositories import runs as runs_repo
from backend.db.session import Database
from backend.db.store import DbSession, IntegrityError
from backend.enums import RunStatus
from backend.services.runner import Runner

router = APIRouter(tags=["runs"])


@router.get("/runs", response_model=Page[RunOut])
async def list_runs(
    status: str | None = None,
    batch_id: str | None = None,
    use_case: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    s: DbSession = Depends(db_session),
) -> Page[RunOut]:
    rows, total = await runs_repo.list_(
        s, status=status, batch_id=batch_id, use_case=use_case, limit=limit, offset=offset
    )
    names = await subject_names(s, [(r.subject_type, r.subject_id) for r in rows])
    items = [
        RunOut.of(r).model_copy(update={"subject_name": names.get(r.subject_id)}) for r in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str, s: DbSession = Depends(db_session)) -> RunOut:
    run = await runs_repo.get(s, run_id)
    if run is None:
        raise not_found("run", run_id)
    names = await subject_names(s, [(run.subject_type, run.subject_id)])
    return RunOut.of(run).model_copy(update={"subject_name": names.get(run.subject_id)})


@router.post("/runs/{run_id}/retry", response_model=RunOut, status_code=202)
async def retry_run(
    run_id: str,
    db: Database = Depends(get_database),
    runner: Runner | None = Depends(get_runner),
    actor: str | None = Depends(optional_actor),
) -> RunOut:
    try:
        async with db.session() as s:
            run = await runs_repo.get(s, run_id)
            if run is None:
                raise not_found("run", run_id)
            if run.status != RunStatus.FAILED:
                raise AppError(
                    409, "conflict", f"Only failed runs can be retried (run is {run.status})."
                )
            run = await runs_repo.reset_for_retry(s, run_id)
            if run is None:  # status changed under us
                raise AppError(409, "conflict", "Run changed state; refresh and try again.")
            audit_repo.add_event(
                s,
                event_type="run.retried",
                run_id=run_id,
                subject_type=run.subject_type,
                subject_id=run.subject_id,
                actor=actor or "system",
            )
            out = RunOut.of(run)
    except IntegrityError as e:
        raise AppError(409, "conflict", "Another run for this subject is already active.") from e
    if runner:
        runner.notify()
    return out


@router.get("/batches/{batch_id}", response_model=BatchOut)
async def get_batch(batch_id: str, s: DbSession = Depends(db_session)) -> BatchOut:
    batch = await s.get(Batch, batch_id)
    if batch is None:
        raise not_found("batch", batch_id)
    counts = await runs_repo.status_counts(s, batch_id)
    rows, _ = await runs_repo.list_(s, batch_id=batch_id, limit=10_000)
    return BatchOut.of(batch, counts, [r.id for r in rows])
