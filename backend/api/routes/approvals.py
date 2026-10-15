"""Approve / reject / edit. Actor comes from the X-Session-Id session, never the body."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.deps import get_database, get_runner
from backend.api.errors import AppError
from backend.api.session_auth import Actor, require_actor
from backend.db.session import Database
from backend.enums import Decision
from backend.services import approvals as svc
from backend.services.runner import Runner

router = APIRouter(prefix="/approvals", tags=["approvals"])


class DecisionIn(BaseModel):
    expected_version: int | None = Field(
        default=None, description="Version the reviewer saw; mismatch -> 409."
    )
    reason: str | None = Field(default=None, max_length=1000)


class EditIn(DecisionIn):
    edits: dict[str, Any] = Field(
        description="Any of: action, channel, discount_pct, draft_message, draft_subject."
    )


class DecisionOut(BaseModel):
    recommendation_id: str
    status: str
    version: int
    approval_id: str
    message_id: str | None


async def _decide(
    db: Database,
    runner: Runner | None,
    rec_id: str,
    actor: Actor,
    decision: Decision,
    body: DecisionIn,
    edits: dict[str, Any] | None = None,
) -> DecisionOut:
    try:
        r = await svc.decide(
            db,
            rec_id,
            actor,
            decision,
            expected_version=body.expected_version,
            reason=body.reason,
            edits=edits,
        )
    except svc.DecisionError as e:
        raise AppError(e.status, e.code, e.message, e.details) from e
    if r.message and runner:
        runner.notify_outbox()
    return DecisionOut(
        recommendation_id=r.recommendation.id,
        status=r.recommendation.status,
        version=r.recommendation.version,
        approval_id=r.approval.id,
        message_id=r.message.id if r.message else None,
    )


@router.post("/{rec_id}/approve", response_model=DecisionOut)
async def approve(
    rec_id: str,
    body: DecisionIn | None = None,
    actor: Actor = Depends(require_actor),
    db: Database = Depends(get_database),
    runner: Runner | None = Depends(get_runner),
) -> DecisionOut:
    return await _decide(db, runner, rec_id, actor, Decision.APPROVED, body or DecisionIn())


@router.post("/{rec_id}/reject", response_model=DecisionOut)
async def reject(
    rec_id: str,
    body: DecisionIn,
    actor: Actor = Depends(require_actor),
    db: Database = Depends(get_database),
    runner: Runner | None = Depends(get_runner),
) -> DecisionOut:
    return await _decide(db, runner, rec_id, actor, Decision.REJECTED, body)


@router.post("/{rec_id}/edit", response_model=DecisionOut)
async def edit(
    rec_id: str,
    body: EditIn,
    actor: Actor = Depends(require_actor),
    db: Database = Depends(get_database),
    runner: Runner | None = Depends(get_runner),
) -> DecisionOut:
    return await _decide(db, runner, rec_id, actor, Decision.APPROVED_WITH_EDITS, body, body.edits)
