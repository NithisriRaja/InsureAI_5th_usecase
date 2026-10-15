from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from backend.config import get_settings
from backend.db.session import Database
from backend.tests.fixtures.fake_llm import fake_llm, smart_responder
from main import create_app


class Switch:
    """Lets a test swap the fake LLM behaviour mid-flight."""

    def __init__(self) -> None:
        self.responder: Callable[..., Any] = smart_responder

    def __call__(self, purpose: str, messages: Any) -> Any:
        return self.responder(purpose, messages)


@pytest.fixture
def llm_switch() -> Switch:
    return Switch()


@pytest.fixture(autouse=True)
def _fast_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNNER_POLL_INTERVAL_S", "0.05")
    monkeypatch.setenv("RUNNER_WORKERS", "3")
    monkeypatch.setenv("RUN_HEARTBEAT_S", "0.2")
    get_settings.cache_clear()


async def _client(db: Database, switch: Switch, start_runner: bool) -> AsyncIterator[Any]:
    llm, _ = fake_llm(switch)
    app = create_app(db=db, llm_factory=lambda: llm, start_runner=start_runner)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
async def api(seeded_db: Database, llm_switch: Switch) -> AsyncIterator[httpx.AsyncClient]:
    """API with the background runner processing runs."""
    async for c in _client(seeded_db, llm_switch, start_runner=True):
        yield c


@pytest.fixture
async def api_queue_only(
    seeded_db: Database, llm_switch: Switch
) -> AsyncIterator[httpx.AsyncClient]:
    """API without a runner: runs stay queued (for race / idempotency tests)."""
    async for c in _client(seeded_db, llm_switch, start_runner=False):
        yield c


async def wait_run(c: httpx.AsyncClient, run_id: str, timeout: float = 10.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        r = (await c.get(f"/runs/{run_id}")).json()
        if r["status"] in ("succeeded", "failed", "skipped"):
            return r
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"run {run_id} stuck in {r['status']}")
        await asyncio.sleep(0.05)


async def wait_batch(c: httpx.AsyncClient, batch_id: str, timeout: float = 15.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        b = (await c.get(f"/batches/{batch_id}")).json()
        if b["done"]:
            return b
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"batch {batch_id} not done: {b['counts']}")
        await asyncio.sleep(0.05)
