"""The process-wide data store: CSV files in ``settings.data_dir``, loaded into memory.

See ``backend.db.store`` for how persistence and concurrency work.
"""

from __future__ import annotations

from pathlib import Path

from backend.config import get_settings
from backend.db.models import MODELS
from backend.db.store import DbSession, IntegrityError, Store

__all__ = ["Database", "DbSession", "IntegrityError", "get_db", "set_db"]


class Database(Store):
    def __init__(self, data_dir: Path | str | None) -> None:
        super().__init__(data_dir, MODELS)


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(get_settings().data_dir)
    return _db


def set_db(db: Database | None) -> None:
    """Swap the process-wide database (tests)."""
    global _db
    _db = db
