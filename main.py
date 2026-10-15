"""FastAPI entry point. From this folder: ``python -m uvicorn main:app --reload``."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import errors
from backend.api.routes import (
    approvals,
    dashboard,
    health,
    insights,
    kpi,
    overview,
    recommendations,
    renewals,
    runs,
    sessions,
)
from backend.config import get_settings
from backend.db.session import Database, get_db, set_db
from backend.services.llm.client import LLMClient
from backend.services.runner import Runner
from backend.utils.logging import configure_logging, get_logger

log = get_logger(__name__)


def create_app(
    *,
    db: Database | None = None,
    llm_factory: Callable[[], LLMClient] | None = None,
    start_runner: bool = True,
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        database = db or get_db()
        set_db(database)
        await database.create_all()
        app.state.db = database
        app.state.runner = None
        if start_runner:
            runner = Runner(database, settings=settings, llm_factory=llm_factory)
            await runner.start()
            app.state.runner = runner
        log.info("app.started", provider=settings.llm_provider, data=database.location)
        try:
            yield
        finally:
            if app.state.runner:
                await app.state.runner.stop()
            if db is None:
                await database.dispose()

    app = FastAPI(
        title="Insurance AI Agents POC",
        version="0.1.0",
        description="Renewal / retention agents with hard rules, LLM decisions and human "
        "approval.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    errors.install(app)
    for r in (
        health.router,
        sessions.router,
        renewals.router,
        runs.router,
        recommendations.router,
        approvals.router,
        insights.router,
        dashboard.router,
        kpi.router,
        overview.router,
    ):
        app.include_router(r)
    return app


app = create_app()
