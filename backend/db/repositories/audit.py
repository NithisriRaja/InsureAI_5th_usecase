from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from backend.db.models import AuditEvent, LLMCall
from backend.db.store import DbSession


def add_event(
    s: DbSession,
    *,
    event_type: str,
    run_id: str | None = None,
    recommendation_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    node: str | None = None,
    actor: str = "system",
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        event_type=event_type,
        run_id=run_id,
        recommendation_id=recommendation_id,
        subject_type=subject_type,
        subject_id=subject_id,
        node=node,
        actor=actor,
        payload=payload or {},
    )
    s.add(ev)
    return ev


async def query(
    s: DbSession,
    *,
    run_id: str | None = None,
    recommendation_id: str | None = None,
    subject_id: str | None = None,
    limit: int = 500,
) -> Sequence[AuditEvent]:
    rows = s.where(
        AuditEvent,
        lambda e: (not run_id or e.run_id == run_id)
        and (not recommendation_id or e.recommendation_id == recommendation_id)
        and (not subject_id or e.subject_id == subject_id),
    )
    return sorted(rows, key=lambda e: e.id)[:limit]


async def llm_calls_for_run(s: DbSession, run_id: str) -> Sequence[LLMCall]:
    return sorted(s.where(LLMCall, lambda c: c.run_id == run_id), key=lambda c: c.created_at)
