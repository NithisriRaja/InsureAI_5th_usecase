from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from backend.api.deps import db_session, get_database, get_runner
from backend.api.errors import AppError, not_found
from backend.api.naming import subject_names
from backend.api.schemas.common import BatchOut, Page, RecBrief, RunBrief, RunOut
from backend.api.schemas.renewals import (
    CrmActivityOut,
    DocumentsIn,
    DocumentsOut,
    PaymentOut,
    PolicyDetail,
    RenewalItem,
    ScanIn,
)
from backend.api.session_auth import Actor, optional_actor, require_actor
from backend.db.models import CrmActivity, Policy, Recommendation
from backend.db.repositories import audit as audit_repo
from backend.db.repositories import policies as policies_repo
from backend.db.repositories import recommendations as recs_repo
from backend.db.repositories import runs as runs_repo
from backend.db.session import Database
from backend.db.store import DbSession
from backend.enums import EXPIRY_LIFECYCLES, PaymentStatus, Role
from backend.integrations import crm_for, policy_admin_for
from backend.services import intake, lifecycle
from backend.services.rules.renewal import RenewalAssessment
from backend.services.runner import Runner
from backend.utils.clock import today

router = APIRouter(prefix="/renewals", tags=["renewals"])

# Terminal policies stay visible on the worklist for a while around their end date.
TERMINAL_VISIBLE_DAYS = (-60, 45)


@router.post("/scan", response_model=BatchOut, status_code=202)
async def scan(
    body: ScanIn | None = None,
    db: Database = Depends(get_database),
    runner: Runner | None = Depends(get_runner),
    actor: str | None = Depends(optional_actor),
) -> BatchOut:
    async with db.session() as s:
        batch, queued = await intake.scan_renewals(
            s,
            window_days=body.window_days if body else None,
            requested_by=actor,
            rerun_pending=bool(body and body.rerun_pending),
        )
        out = BatchOut.of(batch, {"queued": len(queued)} if queued else {}, [r.id for r in queued])
    if runner and queued:
        runner.notify()
    return out


async def _item(
    s: DbSession,
    p: Policy,
    as_of: date,
    a: RenewalAssessment | None,
    rec: Recommendation | None,
) -> RenewalItem:
    customer = await policies_repo.get_customer(s, p.customer_id)
    product = await policies_repo.get_product(s, p.product_code)
    payments = await policies_repo.payments_for(s, p.id)
    active = await runs_repo.active_for(s, "policy", p.id)
    if rec and a and rec.cycle_key != lifecycle.cycle_key(p.id, a):
        rec = None  # recommendation from a previous lifecycle event
    expiry = p.lifecycle_type in EXPIRY_LIFECYCLES
    change = (p.premium - p.prev_premium) / p.prev_premium * 100 if p.prev_premium and expiry else 0
    return RenewalItem(
        policy_id=p.id,
        policy_number=p.policy_number,
        customer_name=f"{customer.first_name} {customer.last_name}" if customer else "?",
        line=p.line,
        product_code=p.product_code,
        product_name=product.name if product else p.product_code,
        lifecycle_type=p.lifecycle_type,
        payment_frequency=p.payment_frequency,
        channel_owner=p.channel_owner,
        intermediary=p.intermediary,
        status=p.status,
        state=a.state.value if a else "skip",
        skip_reason=a.skip_reason if a else p.status,
        triggers=[t.type.value for t in a.triggers] if a else [],
        next_event_type=a.next_event_type if a else None,
        next_event_date=a.next_event_date if a else None,
        end_date=p.end_date,
        days_to_expiry=(p.end_date - as_of).days if expiry else None,
        premium=p.premium,
        prev_premium=p.prev_premium,
        premium_change_pct=round(change, 1),
        overdue_payments=sum(x.status == PaymentStatus.OVERDUE for x in payments),
        docs_outstanding=list(p.docs_outstanding or []),
        latest_recommendation=RecBrief.of(rec),
        active_run=RunBrief.of(active),
    )


def _visible(p: Policy, a: RenewalAssessment | None, as_of: date) -> bool:
    if a is None:
        lo, hi = TERMINAL_VISIBLE_DAYS
        return lo <= (p.end_date - as_of).days <= hi
    return a.skip_reason is None


@router.get("", response_model=Page[RenewalItem])
async def worklist(
    window_days: int | None = Query(None, ge=1, le=365),
    line: str | None = None,
    lifecycle_type: str | None = None,
    channel_owner: str | None = None,
    status: str | None = None,
    q: str | None = Query(None, max_length=100, description="Customer name or policy number"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    s: DbSession = Depends(db_session),
) -> Page[RenewalItem]:
    """Policies with a lifecycle event that needs attention today (plus recently renewed /
    cancelled ones for context), soonest event first."""
    as_of = today()
    policies = list(await policies_repo.list_all(s))
    live = [p for p in policies if p.status not in lifecycle.TERMINAL]
    assessed = await lifecycle.assess_many(s, live, window_days=window_days)
    rows = [p for p in policies if _visible(p, assessed.get(p.id), as_of)]
    if line:
        rows = [p for p in rows if p.line == line]
    if lifecycle_type:
        rows = [p for p in rows if p.lifecycle_type == lifecycle_type]
    if channel_owner:
        rows = [p for p in rows if p.channel_owner == channel_owner]
    if status:
        rows = [p for p in rows if p.status == status]
    if q and q.strip():
        term = q.strip().lower()
        names = await subject_names(s, [("policy", p.id) for p in rows])
        rows = [
            p
            for p in rows
            if term in p.policy_number.lower() or term in names.get(p.id, "").lower()
        ]

    def sort_key(p: Policy) -> tuple[date, str]:
        a = assessed.get(p.id)
        return (a.next_event_date if a and a.next_event_date else p.end_date), p.id

    rows.sort(key=sort_key)
    page = rows[offset : offset + limit]
    recs = await recs_repo.latest_by_subject(s, "policy", [p.id for p in page])
    items = [await _item(s, p, as_of, assessed.get(p.id), recs.get(p.id)) for p in page]
    return Page(items=items, total=len(rows), limit=limit, offset=offset)


@router.get("/{policy_id}", response_model=PolicyDetail)
async def get_policy(policy_id: str, s: DbSession = Depends(db_session)) -> PolicyDetail:
    p = await policies_repo.get(s, policy_id)
    if p is None:
        raise not_found("policy", policy_id)
    as_of = today()
    a = await lifecycle.assess_policy(s, p)
    recs = await recs_repo.latest_by_subject(s, "policy", [p.id])
    base = await _item(s, p, as_of, a, recs.get(p.id))
    customer = await policies_repo.get_customer(s, p.customer_id)
    payments = await policies_repo.payments_for(s, p.id)
    return PolicyDetail(
        **base.model_dump(),
        customer_id=p.customer_id,
        email=customer.email if customer else None,
        phone=customer.phone if customer else None,
        city=customer.city if customer else None,
        consent_marketing=bool(customer and customer.consent_marketing),
        consent_email=bool(customer and customer.consent_email),
        consent_sms=bool(customer and customer.consent_sms),
        preferred_channel=customer.preferred_channel if customer else None,
        start_date=p.start_date,
        sum_insured=p.sum_insured,
        tenure_years=p.tenure_years,
        claims_count_3y=p.claims_count_3y,
        auto_renew=p.auto_renew,
        service_complaints_12m=p.service_complaints_12m,
        review_due_date=p.review_due_date,
        milestone_date=p.milestone_date,
        milestone_label=p.milestone_label,
        add_ons_held=list(p.add_ons_held or []),
        trigger_details=[t.model_dump(mode="json") for t in a.triggers] if a else [],
        allowed_actions=[x.value for x in a.allowed_actions] if a else [],
        in_window=bool(a and a.skip_reason is None),
        payments=[
            PaymentOut(due_date=x.due_date, amount=x.amount, status=x.status, paid_at=x.paid_at)
            for x in payments
        ],
        latest_run=RunBrief.of(await runs_repo.latest_for(s, "policy", p.id)),
    )


@router.post(
    "/{policy_id}/runs",
    response_model=RunOut,
    status_code=202,
    responses={
        200: {"description": "A run is already active; returned as-is"},
        409: {"description": "Policy has no lifecycle event due (reason in details)"},
    },
)
async def run_policy(
    policy_id: str,
    response: Response,
    db: Database = Depends(get_database),
    runner: Runner | None = Depends(get_runner),
    actor: str | None = Depends(optional_actor),
) -> RunOut:
    async with db.session() as s:
        policy = await policies_repo.get(s, policy_id)
        if policy is None:
            raise not_found("policy", policy_id)
        run, created, reason = await intake.enqueue_renewal(s, policy, requested_by=actor)
        if run is None:
            raise AppError(
                409,
                "not_due",
                f"Policy {policy.policy_number} has no lifecycle event due: {reason}.",
                {"reason": reason},
            )
        out = RunOut.of(run)
    if not created:
        response.status_code = 200
    elif runner:
        runner.notify()
    return out


DOCUMENT_ROLES = {Role.RETENTION, Role.ADVISER, Role.ADMIN}


@router.post("/{policy_id}/documents", response_model=DocumentsOut)
async def documents_received(
    policy_id: str,
    body: DocumentsIn,
    actor: Actor = Depends(require_actor),
    db: Database = Depends(get_database),
) -> DocumentsOut:
    """Record documents the customer sent in. Clears them from the policy (policy admin),
    logs it on the CRM record, and the next scan no longer chases them."""
    if actor.role not in DOCUMENT_ROLES:
        raise AppError(403, "forbidden", f"Role '{actor.role}' cannot record documents.")
    async with db.session() as s:
        policy = await policies_repo.get(s, policy_id)
        if policy is None:
            raise not_found("policy", policy_id)
        unknown = sorted(set(body.received) - set(policy.docs_outstanding))
        if unknown:
            raise AppError(
                422,
                "validation_error",
                f"Not outstanding on this policy: {unknown}",
                {"docs_outstanding": policy.docs_outstanding},
            )
    outstanding = await policy_admin_for(db).mark_documents_received(policy_id, body.received)
    who = f"{actor.name} ({actor.role})"
    async with db.session() as s:
        audit_repo.add_event(
            s,
            event_type="documents.received",
            subject_type="policy",
            subject_id=policy_id,
            actor=who,
            payload={"received": body.received, "outstanding": outstanding},
        )
    await crm_for(db).log_activity(
        kind="documents_received",
        policy_id=policy_id,
        summary="Documents received: " + ", ".join(body.received),
        actor=who,
    )
    return DocumentsOut(policy_id=policy_id, received=body.received, docs_outstanding=outstanding)


@router.get("/{policy_id}/crm", response_model=list[CrmActivityOut])
async def crm_activity(policy_id: str, s: DbSession = Depends(db_session)) -> list[CrmActivityOut]:
    """What the workflow agent wrote back to the CRM for this policy, newest first."""
    if await policies_repo.get(s, policy_id) is None:
        raise not_found("policy", policy_id)
    rows = s.where(CrmActivity, lambda a: a.policy_id == policy_id)
    rows.sort(key=lambda a: a.created_at, reverse=True)
    return [
        CrmActivityOut(
            id=a.id,
            kind=a.kind,
            channel=a.channel,
            summary=a.summary,
            actor=a.actor,
            recommendation_id=a.recommendation_id,
            created_at=a.created_at,
        )
        for a in rows
    ]
