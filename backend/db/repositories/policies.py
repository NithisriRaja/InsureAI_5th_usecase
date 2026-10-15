from __future__ import annotations

from collections.abc import Sequence

from backend.db.models import Customer, Payment, Policy, Product
from backend.db.store import DbSession


async def get(s: DbSession, policy_id: str) -> Policy | None:
    return await s.get(Policy, policy_id)


async def get_customer(s: DbSession, customer_id: str) -> Customer | None:
    return await s.get(Customer, customer_id)


async def get_product(s: DbSession, code: str) -> Product | None:
    return await s.get(Product, code)


async def list_products(s: DbSession, *, line: str | None = None) -> Sequence[Product]:
    rows = s.where(Product, lambda p: p.active and (not line or p.line == line))
    return sorted(rows, key=lambda p: p.code)


async def payments_for(s: DbSession, policy_id: str) -> Sequence[Payment]:
    return sorted(s.where(Payment, lambda p: p.policy_id == policy_id), key=lambda p: p.due_date)


async def list_all(s: DbSession) -> Sequence[Policy]:
    """Every policy; the lifecycle rules (not this query) decide what is due."""
    return sorted(s.all(Policy), key=lambda p: p.id)


async def list_(
    s: DbSession, *, limit: int = 50, offset: int = 0, status: str | None = None
) -> tuple[Sequence[Policy], int]:
    rows = sorted(
        s.where(Policy, lambda p: not status or p.status == status),
        key=lambda p: (p.end_date, p.id),
    )
    return rows[offset : offset + limit], len(rows)
