"""Trigger logic shared by API routes and demo scripts: renewal scans and single-policy runs."""

from __future__ import annotations

from typing import Any

from backend.config import get_settings
from backend.db.models import Batch, Policy, Run
from backend.db.repositories import audit as audit_repo
from backend.db.repositories import policies as policies_repo
from backend.db.repositories import recommendations as recs_repo
from backend.db.repositories import runs as runs_repo
from backend.db.store import DbSession
from backend.enums import BatchKind, PolicyStatus, SubjectType, UseCase
from backend.services import lifecycle
from backend.utils.clock import today
from backend.utils.ids import new_id


async def enqueue_renewal(
    s: DbSession,
    policy: Policy,
    *,
    requested_by: str | None = None,
    batch_id: str | None = None,
) -> tuple[Run | None, bool, str | None]:
    """Queue one policy's lifecycle run. Returns (run, created, skip_reason).

    Same gates as the scan: a skip reason means nothing was queued. An open (undecided)
    recommendation is fine to re-run; finalize supersedes it.
    """
    a = await lifecycle.assess_policy(s, policy)
    if a is None:
        return None, False, "missing_customer_or_product"
    lifecycle.record_next_event(policy, a)
    reason = a.skip_reason
    cycle = lifecycle.cycle_key(policy.id, a)
    if reason is None and await recs_repo.decided_for_cycle(s, "policy", policy.id, cycle):
        reason = "already_decided"
    if reason is not None:
        return None, False, reason
    run, created = await runs_repo.enqueue(
        s,
        use_case=UseCase.RENEWAL,
        subject_type=SubjectType.POLICY,
        subject_id=policy.id,
        cycle_key=cycle,
        max_attempts=get_settings().run_max_attempts,
        requested_by=requested_by,
        batch_id=batch_id,
    )
    return run, created, None


# Not-due reasons that are routine (not worth listing as "skipped" in a scan batch).
QUIET_SKIPS = ("out_of_window", "no_trigger", "lapsed_beyond_lookback")


async def scan_renewals(
    s: DbSession,
    *,
    window_days: int | None = None,
    requested_by: str | None = None,
    rerun_pending: bool = False,
) -> tuple[Batch, list[Run]]:
    """Lifecycle monitor: assess every in-force policy, queue one run per fired event.

    ``rerun_pending`` also re-runs events whose recommendation is still waiting for approval
    (the workflow agent supersedes it); decided events are never re-run."""
    as_of = today()
    window = window_days or get_settings().renewal_window_days
    batch = Batch(
        id=new_id("bat"),
        kind=BatchKind.RENEWAL_SCAN.value,
        params={"as_of": as_of.isoformat(), "window_days": window},
        requested_by=requested_by,
    )
    s.add(batch)
    await s.flush()

    queued: list[Run] = []
    skipped: list[dict[str, Any]] = []
    for p in await policies_repo.list_all(s):
        if p.status in lifecycle.TERMINAL:
            reason = "cancelled" if p.status == PolicyStatus.CANCELLED else "already_renewed"
            if -60 <= (p.end_date - as_of).days <= (window or 45):  # recent terms only
                skipped.append(
                    {"subject_id": p.id, "policy_number": p.policy_number, "reason": reason}
                )
            continue
        a = await lifecycle.assess_policy(s, p, window_days=window)
        if a is None:
            continue
        lifecycle.record_next_event(p, a)
        if a.skip_reason in QUIET_SKIPS:
            continue
        cycle = lifecycle.cycle_key(p.id, a)
        reason = a.skip_reason
        if (
            reason is None
            and not rerun_pending
            and await recs_repo.open_for_cycle(s, "policy", p.id, cycle)
        ):
            reason = "open_recommendation"
        if reason is None and await recs_repo.decided_for_cycle(s, "policy", p.id, cycle):
            reason = "already_decided"
        if reason is None:
            run, created = await runs_repo.enqueue(
                s,
                use_case=UseCase.RENEWAL,
                subject_type=SubjectType.POLICY,
                subject_id=p.id,
                cycle_key=cycle,
                max_attempts=get_settings().run_max_attempts,
                batch_id=batch.id,
                requested_by=requested_by,
            )
            if created:
                queued.append(run)
                continue
            reason = "active_run"
        skipped.append({"subject_id": p.id, "policy_number": p.policy_number, "reason": reason})
    batch.skipped = skipped
    audit_repo.add_event(
        s,
        event_type="renewal.scan",
        actor=requested_by or "system",
        payload={
            "batch_id": batch.id,
            "queued": len(queued),
            "skipped": len(skipped),
            "window_days": window,
        },
    )
    return batch, queued
