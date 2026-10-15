from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from backend.api.deps import get_database
from backend.api.errors import AppError
from backend.api.session_auth import Actor, require_actor
from backend.config import get_settings
from backend.db.repositories import audit as audit_repo
from backend.db.repositories import identity as identity_repo
from backend.db.session import Database
from backend.enums import Role

router = APIRouter(tags=["sessions"])


class SessionIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: Role


class UserOut(BaseModel):
    id: str
    name: str
    role: str


class SessionOut(BaseModel):
    session_id: str
    user: UserOut
    expires_at: datetime


class ActiveUser(BaseModel):
    id: str
    name: str
    role: str
    last_seen_at: datetime


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    body: SessionIn, request: Request, db: Database = Depends(get_database)
) -> SessionOut:
    if not body.name.strip():
        raise AppError(422, "validation_error", "Name must not be blank.")
    async with db.session() as s:
        user, previous_role = await identity_repo.upsert_user(s, body.name, body.role.value)
        sess = await identity_repo.create_session(
            s,
            user=user,
            idle_hours=get_settings().session_idle_hours,
            user_agent=request.headers.get("user-agent"),
        )
        audit_repo.add_event(
            s,
            event_type="session.started",
            actor=user.name,
            payload={"user_id": user.id, "role": user.role, "previous_role": previous_role},
        )
        return SessionOut(
            session_id=sess.id,
            expires_at=sess.expires_at,
            user=UserOut(id=user.id, name=user.name, role=user.role),
        )


@router.get("/sessions/me", response_model=UserOut)
async def me(actor: Actor = Depends(require_actor)) -> UserOut:
    return UserOut(id=actor.user_id, name=actor.name, role=actor.role)


@router.post("/sessions/heartbeat", response_model=UserOut)
async def heartbeat(actor: Actor = Depends(require_actor)) -> UserOut:
    """``require_actor`` already slid the expiry (throttled write)."""
    return UserOut(id=actor.user_id, name=actor.name, role=actor.role)


@router.delete("/sessions/current", status_code=204)
async def end_session(
    x_session_id: str | None = Header(default=None), db: Database = Depends(get_database)
) -> None:
    async with db.session() as s:
        found = await identity_repo.get_active(s, x_session_id)
        if found:
            await identity_repo.end(s, found[0])


@router.get("/users/active", response_model=list[ActiveUser])
async def active_users(db: Database = Depends(get_database)) -> list[ActiveUser]:
    async with db.session() as s:
        rows = await identity_repo.active_users(s)
        return [
            ActiveUser(id=u.id, name=u.name, role=u.role, last_seen_at=sess.last_seen_at)
            for u, sess in rows
        ]
