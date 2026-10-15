"""Read-only business aggregations for the operations dashboard.

Every number here is a COUNT / SUM over stored rows; nothing is projected or estimated. Money
is returned in minor units (cents), like the rest of the API.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend import rulebook
from backend.api.deps import db_session
from backend.api.naming import subject_names
from backend.config import get_settings
from backend.db.models import (
    Approval,
    AuditEvent,
    Message,
    Payment,
    Policy,
    Recommendation,
    Run,
)
from backend.db.store import DbSession
from backend.enums import (
    EXPIRY_LIFECYCLES,
    LifecycleType,
    PaymentStatus,
    PolicyStatus,
    RecStatus,
)
from backend.services import lifecycle
from backend.utils.clock import today, utcnow

router = APIRouter(tags=["dashboard"])

# Recommendations that no longer represent the current view of a subject.
_HISTORIC = (RecStatus.SUPERSEDED, RecStatus.EXPIRED)
_ACTIVITY_TYPES = (
    "renewal.scan",
    "run.failed",
    "recommendation.created",
    "recommendation.approved",
    "recommendation.approved_with_edits",
    "recommendation.rejected",
    "recommendation.expired",
    "recommendation.superseded",
    "message.delivered",
    "message.failed",
)


class Count(BaseModel):
    key: str
    count: int


class QueueLoad(BaseModel):
    queue: str
    high: int = 0
    medium: int = 0
    low: int = 0


class ExpiryBucket(BaseModel):
    key: str  # past | 0_7 | 8_30 | 31_window | later
    label: str
    count: int
    premium: int  # renewal premium, minor units


class PolicyStats(BaseModel):
    total: int
    by_status: list[Count]
    by_line: list[Count]
    by_lifecycle: list[Count]
    by_channel_owner: list[Count]
    due_by_trigger: list[Count]  # fired lifecycle events across due policies
    in_force: int
    in_force_premium: int  # current-term premium of active + grace policies, minor units
    in_force_sum_insured: int
    due_for_renewal: int  # policies with a lifecycle event a scan would pick up today
    due_renewal_premium: int
    due_avg_premium_change_pct: float | None
    expiry: list[ExpiryBucket]
    with_overdue_payments: int
    overdue_amount: int
    with_docs_outstanding: int


class RecStats(BaseModel):
    by_status: list[Count]
    pending: int
    pending_high: int
    pending_by_queue: list[QueueLoad]
    needs_review_pending: int
    expiring_24h: int
    renewal_bands: list[Count]
    actions: list[Count]


class DecisionStats(BaseModel):
    approved: int
    approved_with_edits: int
    rejected: int
    approval_rate_pct: float | None


class RunStats(BaseModel):
    by_status: list[Count]
    by_use_case: list[Count]
    avg_duration_s: float | None


class ActivityItem(BaseModel):
    id: int
    ts: datetime
    event_type: str
    actor: str
    subject_type: str | None
    subject_id: str | None
    subject_name: str | None
    recommendation_id: str | None
    run_id: str | None


class Outcomes(BaseModel):
    """Human-review outcomes for one use case."""

    pending: int
    approved: int  # approved + approved with changes
    rejected: int
    messages_sent: int  # delivered or sent to the customer


class OfferStats(BaseModel):
    count: int
    avg_discount_pct: float | None
    customer_savings: int  # sum of (premium_before - premium_after), minor units
    premium_kept: int  # sum of discounted premiums if accepted, minor units


class RenewalStats(BaseModel):
    """Policy renewal, retention, personalised offers."""

    due: int
    checked: int  # due policies with an AI suggestion for the current term
    in_progress: int
    failed: int
    lapse_bands: list[Count]
    next_steps: list[Count]
    offers: OfferStats
    review: Outcomes


class Dashboard(BaseModel):
    as_of: date
    renewal_window_days: int
    renewal: RenewalStats
    policies: PolicyStats
    recommendations: RecStats
    decisions: DecisionStats
    messages: list[Count]
    runs: RunStats
    activity: list[ActivityItem]


def _counts(values: Iterable[Any]) -> list[Count]:
    return [
        Count(key=str(k) if k is not None else "unknown", count=n)
        for k, n in Counter(values).most_common()
    ]


def _bucket_labels(window: int) -> dict[str, str]:
    return {
        "past": "Already ended",
        "0_7": "Next 7 days",
        "8_30": "8–30 days",
        "31_window": f"31–{window} days",
        "later": f"After {window} days",
    }


def _bucket(days: int, window: int) -> str:
    if days < 0:
        return "past"
    if days <= 7:
        return "0_7"
    if days <= 30:
        return "8_30"
    return "31_window" if days <= window else "later"


async def _due(s: DbSession) -> dict[str, Any]:
    """Policies with a lifecycle event due today (same rules as the scan)."""
    assessed = await lifecycle.assess_many(s, await lifecycle.monitored_policies(s))
    return {pid: a for pid, a in assessed.items() if a.skip_reason is None}


async def _policy_stats(
    s: DbSession, as_of: date, window: int, due_ids: dict[str, Any]
) -> PolicyStats:
    policies = s.all(Policy)
    overdue: Counter[str] = Counter()
    for pay in s.where(Payment, lambda p: p.status == PaymentStatus.OVERDUE):
        overdue[pay.policy_id] += pay.amount
    in_force = [p for p in policies if p.status in (PolicyStatus.ACTIVE, PolicyStatus.GRACE)]
    due = [p for p in policies if p.id in due_ids]
    changes = [
        (p.premium - p.prev_premium) / p.prev_premium * 100
        for p in due
        if p.prev_premium and p.lifecycle_type in EXPIRY_LIFECYCLES
    ]

    # Every bucket is returned (zero or not) so the chart axis is stable.
    buckets = {
        k: ExpiryBucket(key=k, label=text, count=0, premium=0)
        for k, text in _bucket_labels(window).items()
    }
    lookback_start = as_of - timedelta(days=60)
    for p in policies:
        # Only fixed-term products have an expiry; renewed / cancelled / old terms are skipped.
        if (
            p.lifecycle_type not in EXPIRY_LIFECYCLES
            or p.status in (PolicyStatus.RENEWED, PolicyStatus.CANCELLED)
            or p.end_date < lookback_start
        ):
            continue
        b = buckets[_bucket((p.end_date - as_of).days, window)]
        b.count += 1
        b.premium += p.premium

    by_status = Counter(p.status for p in policies)
    by_line = Counter(p.line for p in policies)
    return PolicyStats(
        total=len(policies),
        by_status=[Count(key=k, count=n) for k, n in by_status.most_common()],
        by_line=[Count(key=k, count=n) for k, n in by_line.most_common()],
        by_lifecycle=_counts([p.lifecycle_type for p in policies]),
        by_channel_owner=_counts([p.channel_owner for p in policies]),
        due_by_trigger=_counts([t.type.value for a in due_ids.values() for t in a.triggers]),
        in_force=len(in_force),
        in_force_premium=sum(p.prev_premium for p in in_force),
        in_force_sum_insured=sum(p.sum_insured for p in in_force),
        due_for_renewal=len(due),
        due_renewal_premium=sum(p.premium for p in due),
        due_avg_premium_change_pct=round(sum(changes) / len(changes), 1) if changes else None,
        expiry=list(buckets.values()),
        with_overdue_payments=len(overdue),
        overdue_amount=sum(overdue.values()),
        with_docs_outstanding=sum(1 for p in policies if p.docs_outstanding),
    )


async def _rec_stats(s: DbSession) -> RecStats:
    recs = s.all(Recommendation)
    pending = [r for r in recs if r.status == RecStatus.PENDING_APPROVAL]
    current = [r for r in recs if r.status not in _HISTORIC]

    loads: dict[str, QueueLoad] = {}
    for r in pending:
        load = loads.setdefault(r.queue, QueueLoad(queue=r.queue))
        if r.priority in ("high", "medium", "low"):
            setattr(load, r.priority, getattr(load, r.priority) + 1)

    soon = utcnow() + timedelta(hours=24)
    return RecStats(
        by_status=_counts(r.status for r in recs),
        pending=len(pending),
        pending_high=sum(r.priority == "high" for r in pending),
        pending_by_queue=sorted(loads.values(), key=lambda x: x.queue),
        needs_review_pending=sum(r.needs_review for r in pending),
        expiring_24h=sum(r.expires_at is not None and r.expires_at <= soon for r in pending),
        renewal_bands=_counts(r.band for r in current if r.use_case == "renewal"),
        actions=_counts(r.action for r in current),
    )


async def _decision_stats(s: DbSession) -> DecisionStats:
    by = Counter(a.decision for a in s.all(Approval))
    approved, edited, rejected = (
        by["approved"],
        by["approved_with_edits"],
        by["rejected"],
    )
    decided = approved + edited + rejected
    return DecisionStats(
        approved=approved,
        approved_with_edits=edited,
        rejected=rejected,
        approval_rate_pct=round((approved + edited) / decided * 100, 1) if decided else None,
    )


async def _run_stats(s: DbSession) -> RunStats:
    runs = s.all(Run)
    durations = [
        (r.finished_at - r.started_at).total_seconds()
        for r in runs
        if r.status == "succeeded" and r.started_at and r.finished_at
    ]
    return RunStats(
        by_status=_counts(r.status for r in runs),
        by_use_case=_counts(r.use_case for r in runs),
        avg_duration_s=round(sum(durations) / len(durations), 1) if durations else None,
    )


async def _activity(s: DbSession, limit: int = 40) -> list[ActivityItem]:
    events = sorted(
        s.where(AuditEvent, lambda e: e.event_type in _ACTIVITY_TYPES),
        key=lambda e: e.id,
        reverse=True,
    )[:limit]
    names = await subject_names(
        s, [(e.subject_type, e.subject_id) for e in events if e.subject_type and e.subject_id]
    )
    return [
        ActivityItem(
            id=e.id,
            ts=e.ts,
            event_type=e.event_type,
            actor=e.actor,
            subject_type=e.subject_type,
            subject_id=e.subject_id,
            subject_name=names.get(e.subject_id or ""),
            recommendation_id=e.recommendation_id,
            run_id=e.run_id,
        )
        for e in events
    ]


async def _latest_recs(s: DbSession, use_case: str) -> list[Recommendation]:
    """Newest still-valid recommendation per subject (replaced / expired ones are history)."""
    newest: dict[str, Recommendation] = {}
    for r in s.where(
        Recommendation, lambda r: r.use_case == use_case and r.status not in _HISTORIC
    ):
        cur = newest.get(r.subject_id)
        if cur is None or r.created_at > cur.created_at:
            newest[r.subject_id] = r
    return list(newest.values())


async def _run_health(s: DbSession, use_case: str) -> tuple[int, int]:
    """(analyses queued or running, subjects whose latest analysis failed)."""
    runs = s.where(Run, lambda r: r.use_case == use_case)
    active = sum(r.status in ("queued", "running") for r in runs)
    latest: dict[str, Run] = {}
    for r in runs:
        cur = latest.get(r.subject_id)
        if cur is None or r.created_at > cur.created_at:
            latest[r.subject_id] = r
    return active, sum(r.status == "failed" for r in latest.values())


async def _outcomes(s: DbSession, use_case: str, subject_type: str) -> Outcomes:
    recs = {r.id: r for r in s.where(Recommendation, lambda r: r.use_case == use_case)}
    by = Counter(a.decision for a in s.all(Approval) if a.recommendation_id in recs)
    return Outcomes(
        pending=sum(r.status == RecStatus.PENDING_APPROVAL for r in recs.values()),
        approved=by["approved"] + by["approved_with_edits"],
        rejected=by["rejected"],
        messages_sent=sum(
            m.subject_type == subject_type and m.status in ("sent", "delivered")
            for m in s.all(Message)
        ),
    )


async def _renewal(s: DbSession, due_ids: dict[str, Any]) -> RenewalStats:
    cycles = {pid: lifecycle.cycle_key(pid, a) for pid, a in due_ids.items()}
    # Only suggestions for each policy's current lifecycle event count.
    recs = [r for r in await _latest_recs(s, "renewal") if cycles.get(r.subject_id) == r.cycle_key]
    due = set(due_ids)
    offers = [r.offer for r in recs if r.action == "retention_offer" and r.offer]
    discounts = [float(o.get("discount_pct") or 0) for o in offers]
    active, failed = await _run_health(s, "renewal")
    return RenewalStats(
        due=len(due),
        checked=sum(r.subject_id in due for r in recs),
        in_progress=active,
        failed=failed,
        lapse_bands=_counts([r.band for r in recs]),
        next_steps=_counts([r.action for r in recs]),
        offers=OfferStats(
            count=len(offers),
            avg_discount_pct=round(sum(discounts) / len(discounts), 1) if discounts else None,
            customer_savings=sum(
                int(o.get("premium_before") or 0) - int(o.get("premium_after") or 0) for o in offers
            ),
            premium_kept=sum(int(o.get("premium_after") or 0) for o in offers),
        ),
        review=await _outcomes(s, "renewal", "policy"),
    )


@router.get("/dashboard", response_model=Dashboard)
async def dashboard(s: DbSession = Depends(db_session)) -> Dashboard:
    as_of = today()
    window = get_settings().renewal_window_days or max(
        rulebook.LIFECYCLES[LifecycleType.EXPIRY_RENEWAL]["notice_days"]
    )
    recs = await _rec_stats(s)
    due = await _due(s)
    return Dashboard(
        as_of=as_of,
        renewal_window_days=window,
        renewal=await _renewal(s, due),
        policies=await _policy_stats(s, as_of, window, due),
        recommendations=recs,
        decisions=await _decision_stats(s),
        messages=_counts(m.status for m in s.all(Message)),
        runs=await _run_stats(s),
        activity=await _activity(s),
    )
