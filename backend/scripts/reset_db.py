"""Delete the CSV data files (start from an empty book).

Stop the API first: it owns the data folder while running.

Usage:
    python -m backend.scripts.reset_db
"""

from __future__ import annotations

from backend.config import get_settings
from backend.db.models import MODELS


def reset() -> None:
    data_dir = get_settings().data_dir
    removed = []
    for model in MODELS:
        path = data_dir / f"{model.__table__}.csv"
        if path.exists():
            path.unlink()
            removed.append(path.name)
    print(f"Removed {len(removed)} file(s) from {data_dir.resolve()}")


if __name__ == "__main__":
    reset()
