from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest

from backend.config import get_settings
from backend.db.session import Database, set_db

AS_OF = date(2026, 10, 13)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic settings for every test; never read the developer's .env."""
    monkeypatch.setenv("AS_OF_DATE", AS_OF.isoformat())
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    for key in ("OPENROUTER_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "backend.config.Settings.model_config",
        {**get_settings().model_config, "env_file": None},
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def db(tmp_path) -> AsyncIterator[Database]:
    """Fresh database per test, persisted to CSV files in a temp folder."""
    database = Database(tmp_path / "data")
    await database.create_all()
    set_db(database)
    yield database
    set_db(None)
    await database.dispose()


@pytest.fixture
async def seeded_db(db: Database) -> Database:
    from backend.seed import seed

    async with db.session() as s:
        await seed(s, "small")
    return db
