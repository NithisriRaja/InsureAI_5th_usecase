"""Users + sessions (lightweight identity, not security).

- One user per case-insensitive name; picking an existing name with a new role updates it.
- Sessions slide: each heartbeat pushes ``expires_at`` forward by the idle timeout.
- Heartbeat writes are throttled so many open tabs don't update the session on every beat.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from backend.db.models import Session, User
from backend.db.store import DbSession
from backend.utils.clock import utcnow
from backend.utils.ids import new_id, new_token

HEARTBEAT_WRITE_THROTTLE = timedelta(seconds=30)
ACTIVE_WINDOW = timedelta(minutes=5)
ENDED_RETENTION = timedelta(days=7)


def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


async def upsert_user(s: DbSession, name: str, role: str) -> tuple[User, str | None]:
    """Returns (user, previous_role if it changed)."""
    key = name_key(name)
    user = next(iter(s.where(User, lambda u: u.name_key == key)), None)
    if user is None:
        user = User(id=new_id("usr"), name=" ".join(name.split()), name_key=key, role=role)
        s.add(user)
        return user, None
    previous = None
    if user.role != role:
        previous, user.role = user.role, role
    return user, previous


async def create_session(
    s: DbSession, *, user: User, idle_hours: float, user_agent: str | None
) -> Session:
    now = utcnow()
    sess = Session(
        id=new_token(),
        user_id=user.id,
        user_agent=(user_agent or "")[:255] or None,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=idle_hours),
    )
    s.add(sess)
    return sess


async def get_active(s: DbSession, token: str | None) -> tuple[Session, User] | None:
    if not token:
        return None
    sess = await s.get(Session, token)
    user = await s.get(User, sess.user_id) if sess else None
    if sess is None or user is None:
        return None
    if sess.ended_at is not None or sess.expires_at <= utcnow():
        return None
    return sess, user


async def touch(s: DbSession, sess: Session, idle_hours: float) -> bool:
    """Slide expiry. Returns True if a write happened (throttled)."""
    now = utcnow()
    if now - sess.last_seen_at < HEARTBEAT_WRITE_THROTTLE:
        return False
    sess.last_seen_at = now
    sess.expires_at = now + timedelta(hours=idle_hours)
    return True


async def end(s: DbSession, sess: Session) -> None:
    sess.ended_at = utcnow()


async def active_users(s: DbSession) -> Sequence[tuple[User, Session]]:
    cutoff = utcnow() - ACTIVE_WINDOW
    live = s.where(Session, lambda x: x.ended_at is None and x.last_seen_at >= cutoff)
    seen: set[str] = set()
    out = []
    for sess in sorted(live, key=lambda x: x.last_seen_at, reverse=True):
        user = await s.get(User, sess.user_id)
        if user is not None and user.id not in seen:
            seen.add(user.id)
            out.append((user, sess))
    return out


async def purge_expired_sessions(s: DbSession) -> int:
    now = utcnow()
    old = now - ENDED_RETENTION
    gone = s.where(
        Session, lambda x: x.expires_at < old or (x.ended_at is not None and x.ended_at < old)
    )
    for sess in gone:
        s.delete(sess)
    return len(gone)
