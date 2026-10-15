"""Write audit events in their own short transaction, attributed to the current run/node."""

from __future__ import annotations

from typing import Any

from backend.db.repositories import audit as audit_repo
from backend.db.session import Database
from backend.utils.context import current_node, current_run_id
from backend.utils.logging import get_logger

log = get_logger(__name__)


async def audit(
    db: Database,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    recommendation_id: str | None = None,
    actor: str = "system",
) -> None:
    log.info(event_type, **{k: v for k, v in (payload or {}).items() if k != "detail"})
    async with db.session() as s:
        audit_repo.add_event(
            s,
            event_type=event_type,
            run_id=current_run_id.get(),
            node=current_node.get(),
            subject_type=subject_type,
            subject_id=subject_id,
            recommendation_id=recommendation_id,
            actor=actor,
            payload=payload or {},
        )
