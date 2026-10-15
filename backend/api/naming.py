"""Display names for run/recommendation subjects, resolved in bulk for list views."""

from __future__ import annotations

from collections.abc import Iterable

from backend.db.models import Customer, Policy
from backend.db.store import DbSession


def _policies(s: DbSession, subjects: Iterable[tuple[str, str]]) -> list[Policy]:
    ids = {sid for kind, sid in subjects if kind == "policy"}
    return [p for pid in ids if (p := s.store.tables[Policy].get(pid))]


async def subject_names(s: DbSession, subjects: Iterable[tuple[str, str]]) -> dict[str, str]:
    """``{subject_id: "First Last"}`` for (subject_type, subject_id) pairs; unknown ids omitted."""
    out = {}
    for p in _policies(s, subjects):
        c = await s.get(Customer, p.customer_id)
        if c is not None:
            out[p.id] = f"{c.first_name} {c.last_name}"
    return out


async def subject_lines(s: DbSession, subjects: Iterable[tuple[str, str]]) -> dict[str, str]:
    """``{subject_id: product line}`` for (subject_type, subject_id) pairs."""
    return {p.id: p.line for p in _policies(s, subjects) if p.line}
