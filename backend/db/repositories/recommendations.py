from __future__ import annotations

from collections.abc import Iterable, Sequence

from backend.db.models import Customer, Policy, Recommendation
from backend.db.store import DbSession
from backend.enums import Priority, RecStatus

# Work queues show high priority first, then newest.
_PRIORITY_RANK = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
DECIDED = (RecStatus.APPROVED, RecStatus.APPROVED_WITH_EDITS, RecStatus.REJECTED)


async def get(s: DbSession, rec_id: str) -> Recommendation | None:
    return await s.get(Recommendation, rec_id)


async def latest_by_subject(
    s: DbSession, subject_type: str, subject_ids: Iterable[str]
) -> dict[str, Recommendation]:
    ids = set(subject_ids)
    out: dict[str, Recommendation] = {}
    for r in s.where(Recommendation, lambda r: r.subject_type == subject_type):
        if r.subject_id in ids:
            cur = out.get(r.subject_id)
            if cur is None or r.created_at > cur.created_at:
                out[r.subject_id] = r
    return out


def _for_cycle(
    s: DbSession, subject_type: str, subject_id: str, cycle_key: str, statuses: Iterable[str]
) -> Recommendation | None:
    wanted = set(statuses)
    return next(
        (
            r
            for r in s.all(Recommendation)
            if r.subject_type == subject_type
            and r.subject_id == subject_id
            and r.cycle_key == cycle_key
            and r.status in wanted
        ),
        None,
    )


async def open_for_cycle(
    s: DbSession, subject_type: str, subject_id: str, cycle_key: str
) -> Recommendation | None:
    return _for_cycle(s, subject_type, subject_id, cycle_key, [RecStatus.PENDING_APPROVAL])


async def decided_for_cycle(
    s: DbSession, subject_type: str, subject_id: str, cycle_key: str
) -> Recommendation | None:
    return _for_cycle(s, subject_type, subject_id, cycle_key, DECIDED)


async def list_(
    s: DbSession,
    *,
    status: str | None = None,
    use_case: str | None = None,
    queue: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    line: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Recommendation], int]:
    policy_ids: set[str] | None = None
    if line:
        policy_ids = {p.id for p in s.where(Policy, lambda p: p.line == line)}
    if search and search.strip():
        term = search.strip().lower()
        customers = {c.id: f"{c.first_name} {c.last_name}".lower() for c in s.all(Customer)}
        found = {
            p.id
            for p in s.all(Policy)
            if term in customers.get(p.customer_id, "") or term in p.policy_number.lower()
        }
        policy_ids = found if policy_ids is None else policy_ids & found
    rows = [
        r
        for r in s.all(Recommendation)
        if (policy_ids is None or (r.subject_type == "policy" and r.subject_id in policy_ids))
        and (not status or r.status == status)
        and (not use_case or r.use_case == use_case)
        and (not queue or r.queue == queue)
        and (not priority or r.priority == priority)
    ]
    rows.sort(key=lambda r: (r.created_at, r.id), reverse=True)
    rows.sort(key=lambda r: _PRIORITY_RANK.get(r.priority, 3))  # stable: newest within rank
    return rows[offset : offset + limit], len(rows)
