"""Audit query, mock message outbox and dashboard stats."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.api.deps import db_session, get_database, get_runner
from backend.api.errors import AppError, not_found
from backend.api.naming import subject_lines, subject_names
from backend.api.schemas.common import Page
from backend.db.models import LLMCall, Message, Policy, Recommendation, Run
from backend.db.repositories import audit as audit_repo
from backend.db.repositories import runs as runs_repo
from backend.db.session import Database
from backend.db.store import DbSession
from backend.services.runner import Runner

router = APIRouter(tags=["insights"])


@router.get("/audit")
async def audit(
    run_id: str | None = None,
    recommendation_id: str | None = None,
    subject_id: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
    s: DbSession = Depends(db_session),
) -> list[dict[str, Any]]:
    if not (run_id or recommendation_id or subject_id):
        raise AppError(422, "validation_error", "Pass run_id, recommendation_id or subject_id.")
    events = await audit_repo.query(
        s, run_id=run_id, recommendation_id=recommendation_id, subject_id=subject_id, limit=limit
    )
    return [
        {
            "id": e.id,
            "ts": e.ts.isoformat(),
            "event_type": e.event_type,
            "run_id": e.run_id,
            "recommendation_id": e.recommendation_id,
            "subject_type": e.subject_type,
            "subject_id": e.subject_id,
            "node": e.node,
            "actor": e.actor,
            "payload": e.payload,
        }
        for e in events
    ]


@router.get("/messages", response_model=Page[dict[str, Any]])
async def messages(
    status: str | None = None,
    line: str | None = Query(None, description="Product line of the policy"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    s: DbSession = Depends(db_session),
) -> Page[dict[str, Any]]:
    in_line = {p.id for p in s.where(Policy, lambda p: p.line == line)} if line else None
    matched = s.where(
        Message,
        lambda m: (not status or m.status == status)
        and (in_line is None or (m.subject_type == "policy" and m.subject_id in in_line)),
    )
    matched.sort(key=lambda m: m.created_at, reverse=True)
    total, rows = len(matched), matched[offset : offset + limit]
    subjects = [(m.subject_type, m.subject_id) for m in rows]
    names = await subject_names(s, subjects)
    lines = await subject_lines(s, subjects)
    items = [
        {
            "id": m.id,
            "recommendation_id": m.recommendation_id,
            "subject_type": m.subject_type,
            "subject_id": m.subject_id,
            "subject_name": names.get(m.subject_id),
            "line": lines.get(m.subject_id),
            "channel": m.channel,
            "recipient": m.recipient,
            "body": m.body,
            "status": m.status,
            "attempts": m.attempts,
            "provider_ref": m.provider_ref,
            "error": m.error,
            "created_at": m.created_at.isoformat(),
            "sent_at": m.sent_at.isoformat() if m.sent_at else None,
        }
        for m in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/messages/{message_id}/retry", status_code=202)
async def retry_message(
    message_id: str,
    db: Database = Depends(get_database),
    runner: Runner | None = Depends(get_runner),
) -> dict[str, str]:
    async with db.session() as s:
        msg = await s.get(Message, message_id)
        if msg is None:
            raise not_found("message", message_id)
        if msg.status != "failed":
            raise AppError(409, "conflict", "Only failed messages can be retried.")
        msg.status, msg.error, msg.attempts = "queued", None, 0
    if runner:
        runner.notify_outbox()
    return {"id": message_id, "status": "queued"}


@router.get("/stats")
async def stats(s: DbSession = Depends(db_session)) -> dict[str, Any]:
    recs = s.all(Recommendation)
    pending = [r for r in recs if r.status == "pending_approval"]
    calls = s.all(LLMCall)
    latencies = [c.latency_ms for c in calls if c.latency_ms is not None]
    failed = sorted(
        (r for r in s.all(Run) if r.status == "failed" and r.finished_at),
        key=lambda r: r.finished_at,
        reverse=True,
    )
    return {
        "runs": await runs_repo.status_counts(s),
        "recommendations_by_status": [
            {"status": k, "count": n} for k, n in Counter(r.status for r in recs).items()
        ],
        "pending_by_queue": [
            {"queue": q, "priority": p, "count": n}
            for (q, p), n in Counter((r.queue, r.priority) for r in pending).items()
        ],
        "needs_review_pending": sum(r.needs_review for r in pending),
        "edits": sum(r.status == "approved_with_edits" for r in recs),
        "messages": dict(Counter(m.status for m in s.all(Message))),
        "llm": {
            "calls": len(calls),
            "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
            "prompt_tokens": sum(c.prompt_tokens or 0 for c in calls),
            "completion_tokens": sum(c.completion_tokens or 0 for c in calls),
            "by_status": dict(Counter(c.status for c in calls)),
        },
        "recent_failed_runs": [
            {"id": r.id, "subject_id": r.subject_id, "error_code": r.error_code}
            for r in failed[:10]
        ],
    }
