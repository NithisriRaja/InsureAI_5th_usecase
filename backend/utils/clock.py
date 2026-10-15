"""Injectable clock so demos and tests can freeze "today" via AS_OF_DATE."""

from __future__ import annotations

from datetime import UTC, date, datetime

from backend.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    as_of = get_settings().as_of_date
    return as_of if as_of is not None else utcnow().date()
