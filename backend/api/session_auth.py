"""Resolve the acting user from the ``X-Session-Id`` header (lightweight identity).

``optional_actor`` is for triggers (attribution only); approvals use ``require_actor``.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header

from backend.api.deps import get_database
from backend.api.errors import AppError
from backend.config import get_settings
from backend.db.repositories import identity as identity_repo
from backend.db.session import Database


@dataclass(frozen=True)
class Actor:
    user_id: str
    name: str
    role: str
    session_id: str


async def resolve(db: Database, token: str | None, *, touch: bool = True) -> Actor | None:
    if not token:
        return None
    async with db.session() as s:
        found = await identity_repo.get_active(s, token)
        if found is None:
            return None
        sess, user = found
        if touch:
            await identity_repo.touch(s, sess, get_settings().session_idle_hours)
        return Actor(user_id=user.id, name=user.name, role=user.role, session_id=sess.id)


async def optional_actor(
    x_session_id: str | None = Header(default=None),
    db: Database = Depends(get_database),
) -> str | None:
    actor = await resolve(db, x_session_id)
    return actor.user_id if actor else None


async def require_actor(
    x_session_id: str | None = Header(default=None),
    db: Database = Depends(get_database),
) -> Actor:
    actor = await resolve(db, x_session_id)
    if actor is None:
        raise AppError(
            401,
            "unauthenticated",
            "No active session. Pick a user (POST /sessions) and send X-Session-Id.",
        )
    return actor
