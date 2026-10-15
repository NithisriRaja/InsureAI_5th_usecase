from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from backend.api.deps import db_session
from backend.api.errors import not_found
from backend.api.naming import subject_lines, subject_names
from backend.api.schemas.common import Page, RunOut
from backend.db.models import Approval, Message, Recommendation, User
from backend.db.repositories import audit as audit_repo
from backend.db.repositories import policies as policies_repo
from backend.db.repositories import recommendations as recs_repo
from backend.db.repositories import runs as runs_repo
from backend.db.store import DbSession
from backend.services import justification

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RecOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    use_case: str
    subject_type: str
    subject_id: str
    cycle_key: str
    status: str
    version: int
    queue: str
    priority: str
    action: str
    channel_owner: str | None
    lifecycle_type: str | None
    band: str | None
    confidence: str | None
    needs_review: bool
    review_reasons: list[Any]
    explanation: str | None
    channel: str | None
    offer: dict[str, Any] | None
    cover_suggestion: dict[str, Any] | None = None
    link: dict[str, Any] | None = None
    expires_at: datetime | None
    created_at: datetime
    decided_at: datetime | None
    subject_name: str | None = None
    line: str | None = None


class RecDetail(RecOut):
    triggers: list[Any]
    rulebook_version: str | None
    signals: dict[str, Any]
    decisions: dict[str, Any]
    rule_results: list[Any]
    draft_subject: str | None
    draft_message: str | None
    fairness: dict[str, Any]
    subject: dict[str, Any] = {}
    decided_by_user: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    message: dict[str, Any] | None = None
    run: RunOut | None = None
    llm_calls: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    justification: dict[str, Any] = {}


@router.get("", response_model=Page[RecOut])
async def list_recommendations(
    status: str | None = "pending_approval",
    use_case: str | None = None,
    queue: str | None = None,
    priority: str | None = None,
    line: str | None = Query(None, description="Product line of the policy"),
    q: str | None = Query(None, max_length=100, description="Customer name or policy number"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    s: DbSession = Depends(db_session),
) -> Page[RecOut]:
    """Default view is the approval queue (``status=pending_approval``); pass ``status=``
    empty for all."""
    rows, total = await recs_repo.list_(
        s,
        status=status or None,
        use_case=use_case,
        queue=queue,
        priority=priority,
        search=q,
        line=line,
        limit=limit,
        offset=offset,
    )
    subjects = [(r.subject_type, r.subject_id) for r in rows]
    names = await subject_names(s, subjects)
    lines = await subject_lines(s, subjects)
    items = [
        RecOut.model_validate(r).model_copy(
            update={"subject_name": names.get(r.subject_id), "line": lines.get(r.subject_id)}
        )
        for r in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


async def _subject(s: DbSession, rec: Recommendation) -> dict[str, Any]:
    policy = await policies_repo.get(s, rec.subject_id)
    if policy is None:
        return {}
    customer = await policies_repo.get_customer(s, policy.customer_id)
    return {
        "type": "policy",
        "id": policy.id,
        "policy_number": policy.policy_number,
        "customer_name": f"{customer.first_name} {customer.last_name}" if customer else "",
        "line": policy.line,
        "product_code": policy.product_code,
        "lifecycle_type": policy.lifecycle_type,
        "payment_frequency": policy.payment_frequency,
        "channel_owner": policy.channel_owner,
        "intermediary": policy.intermediary,
        "review_due_date": policy.review_due_date.isoformat() if policy.review_due_date else None,
        "milestone_date": policy.milestone_date.isoformat() if policy.milestone_date else None,
        "milestone_label": policy.milestone_label,
        "end_date": policy.end_date.isoformat(),
        "premium": policy.premium,
        "prev_premium": policy.prev_premium,
        "status": policy.status,
        "tenure_years": policy.tenure_years,
        "docs_outstanding": policy.docs_outstanding,
    }


@router.get("/{rec_id}", response_model=RecDetail)
async def get_recommendation(rec_id: str, s: DbSession = Depends(db_session)) -> RecDetail:
    rec = await recs_repo.get(s, rec_id)
    if rec is None:
        raise not_found("recommendation", rec_id)
    out = RecDetail.model_validate(rec)
    out.subject = await _subject(s, rec)
    out.subject_name = out.subject.get("customer_name") or None
    out.line = out.subject.get("line") or None
    if rec.decided_by:
        u = await s.get(User, rec.decided_by)
        out.decided_by_user = {"id": u.id, "name": u.name, "role": u.role} if u else None
    apv = next(iter(s.where(Approval, lambda a: a.recommendation_id == rec.id)), None)
    if apv:
        out.approval = {
            "decision": apv.decision,
            "actor": apv.actor_name,
            "role": apv.actor_role,
            "reason": apv.reason,
            "edits": apv.edits,
            "original": apv.original_snapshot,
            "at": apv.created_at.isoformat(),
        }
    msg = next(iter(s.where(Message, lambda m: m.recommendation_id == rec.id)), None)
    if msg:
        out.message = {
            "id": msg.id,
            "channel": msg.channel,
            "status": msg.status,
            "recipient": msg.recipient,
            "provider_ref": msg.provider_ref,
            "error": msg.error,
        }
    run = await runs_repo.get(s, rec.run_id)
    out.run = RunOut.of(run) if run else None
    out.llm_calls = [
        {
            "id": c.id,
            "node": c.node,
            "purpose": c.purpose,
            "provider": c.provider,
            "model": c.model,
            "attempt": c.attempt,
            "status": c.status,
            "error": c.error,
            "latency_ms": c.latency_ms,
            "prompt_tokens": c.prompt_tokens,
            "completion_tokens": c.completion_tokens,
            "request": c.request,
            "response_raw": c.response_raw,
            "parsed": c.parsed,
            "created_at": c.created_at.isoformat(),
        }
        for c in await audit_repo.llm_calls_for_run(s, rec.run_id)
    ]
    events = list(await audit_repo.query(s, run_id=rec.run_id))
    events += [
        e for e in await audit_repo.query(s, recommendation_id=rec.id) if e.run_id != rec.run_id
    ]
    out.audit = [
        {
            "id": e.id,
            "ts": e.ts.isoformat(),
            "event_type": e.event_type,
            "node": e.node,
            "actor": e.actor,
            "payload": e.payload,
        }
        for e in sorted(events, key=lambda e: e.id)
    ]
    out.justification = justification.build(rec, events)
    return out
