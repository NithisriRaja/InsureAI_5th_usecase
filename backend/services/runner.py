"""In-process async run queue workers (DB-backed, crash-recoverable).

- N workers claim queued runs atomically and execute the graph.
- A heartbeat task keeps ``heartbeat_at`` fresh while a run executes.
- On start, runs left ``running`` by a previous process are requeued (or failed once out of
  attempts); a housekeeping loop repeats that for silent workers and purges expired sessions.
- Shutdown stops claiming; in-flight runs get a grace period, then are cancelled and will be
  recovered on next start.
- LLM/rule failures mark the run failed with a machine-readable code; retry is explicit
  (POST /runs/{id}/retry), never automatic, so a failing provider isn't hammered.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import Callable
from typing import Any

from backend.agents.graph import run_graph
from backend.agents.state import GraphDeps
from backend.config import Settings, get_settings
from backend.db.models import Run
from backend.db.repositories import audit as audit_repo
from backend.db.repositories import runs as runs_repo
from backend.db.session import Database
from backend.enums import RunStatus
from backend.integrations.mocks import MockBilling, MockCRM, MockPolicyAdmin
from backend.services.llm.client import LLMClient, get_llm_client
from backend.services.llm.types import LLMError
from backend.services.rules.fairness import FairnessViolation
from backend.utils.logging import get_logger

log = get_logger(__name__)


async def _cancel_and_wait(task: asyncio.Task[Any]) -> None:
    """Cancel a helper task and wait until it has really finished, without swallowing a
    cancellation aimed at the current task."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise


def classify_error(e: BaseException) -> tuple[str, str]:
    if isinstance(e, LLMError):
        return e.code, str(e)
    if isinstance(e, FairnessViolation):
        return "fairness_violation", str(e)
    code = getattr(e, "code", None)
    if isinstance(code, str):
        return code, str(e)
    return "internal_error", f"{type(e).__name__}: {e}"


class Runner:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        llm_factory: Callable[[], LLMClient] | None = None,
        housekeeping_s: float = 15.0,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.llm_factory = llm_factory or get_llm_client
        self.instance = f"w{secrets.token_hex(3)}"
        self.housekeeping_s = housekeeping_s
        self._wake = asyncio.Event()
        self._outbox_wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []
        self._inflight: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------ lifecycle ---

    async def start(self) -> None:
        await self.recover()
        n = max(1, self.settings.runner_workers)
        self._tasks = [asyncio.create_task(self._worker(f"{self.instance}-{i}")) for i in range(n)]
        self._tasks.append(asyncio.create_task(self._housekeeping()))
        self._tasks.append(asyncio.create_task(self._outbox_loop()))
        log.info("runner.started", workers=n, instance=self.instance)

    async def stop(self, grace_s: float = 10.0) -> None:
        self._stopping.set()
        self._wake.set()
        self._outbox_wake.set()
        if self._inflight:
            _, pending = await asyncio.wait(self._inflight, timeout=grace_s)
            for t in pending:
                t.cancel()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, *self._inflight, return_exceptions=True)
        log.info("runner.stopped", instance=self.instance)

    def notify(self) -> None:
        """Wake idle workers immediately after enqueueing."""
        self._wake.set()

    async def recover(self) -> None:
        async with self.db.session() as s:
            requeued, failed = await runs_repo.recover_stale(
                s,
                instance_prefix=self.instance,
                stale_before=runs_repo.stale_cutoff(self.settings.run_stale_after_s),
            )
            for rid in requeued:
                audit_repo.add_event(
                    s, event_type="run.requeued", run_id=rid, payload={"reason": "worker_lost"}
                )
            for rid in failed:
                audit_repo.add_event(
                    s, event_type="run.failed", run_id=rid, payload={"code": "worker_lost"}
                )
        if requeued or failed:
            log.warning("runner.recovered", requeued=requeued, failed=failed)
            self.notify()

    # -------------------------------------------------------------- loops ---

    async def _worker(self, worker_id: str) -> None:
        while not self._stopping.is_set():
            try:
                async with self.db.session() as s:
                    run = await runs_repo.claim_next(s, worker_id)
            except Exception:
                log.exception("runner.claim_failed", worker=worker_id)
                run = None
            if run is None:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self.settings.runner_poll_interval_s)
                continue
            task = asyncio.create_task(self.execute(run, worker_id))
            self._inflight.add(task)
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if self._stopping.is_set():
                    return
                raise
            finally:
                self._inflight.discard(task)

    async def _housekeeping(self) -> None:
        from backend.db.repositories import identity as identity_repo

        while not self._stopping.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), self.housekeeping_s)
            if self._stopping.is_set():
                return
            try:
                await self.recover()
                async with self.db.session() as s:
                    await identity_repo.purge_expired_sessions(s)
            except Exception:
                log.exception("runner.housekeeping_failed")

    async def _outbox_loop(self) -> None:
        from backend.agents.workflow.delivery import MockMessaging, deliver_pending

        gateway = MockMessaging()
        while not self._stopping.is_set():
            self._outbox_wake.clear()
            try:
                await deliver_pending(self.db, gateway, MockCRM(self.db))
            except Exception:
                log.exception("runner.outbox_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._outbox_wake.wait(), 2.0)

    def notify_outbox(self) -> None:
        self._outbox_wake.set()

    async def _heartbeat(self, run_id: str, worker_id: str) -> None:
        while True:
            await asyncio.sleep(self.settings.run_heartbeat_s)
            try:
                async with self.db.session() as s:
                    await runs_repo.heartbeat(s, run_id, worker_id)
            except Exception:
                log.exception("runner.heartbeat_failed", run_id=run_id)

    # ------------------------------------------------------------- execute ---

    async def execute(self, run: Run, worker_id: str) -> None:
        async with self.db.session() as s:
            audit_repo.add_event(
                s,
                event_type="run.started",
                run_id=run.id,
                subject_type=run.subject_type,
                subject_id=run.subject_id,
                payload={"attempt": run.attempts, "worker": worker_id},
            )

        hb = asyncio.create_task(self._heartbeat(run.id, worker_id))
        status, result, code, message = RunStatus.FAILED, {}, None, None
        try:
            deps = GraphDeps(
                db=self.db,
                llm=self.llm_factory(),
                crm=MockCRM(self.db),
                policy_admin=MockPolicyAdmin(self.db),
                billing=MockBilling(self.db),
                renewal_window_days=self.settings.renewal_window_days,
            )
            state = await run_graph(
                run_id=run.id,
                use_case=run.use_case,
                subject_type=run.subject_type,
                subject_id=run.subject_id,
                cycle_key=run.cycle_key,
                deps=deps,
            )
            rec_id = state.get("recommendation_id")
            status = RunStatus.SUCCEEDED if rec_id else RunStatus.SKIPPED
            result = {
                "recommendation_id": rec_id,
                "gate": state.get("gate"),
                "skip_reason": state.get("skip_reason"),
            }
        except asyncio.CancelledError:
            raise  # left 'running'; recovered on next start
        except Exception as e:  # noqa: BLE001
            code, message = classify_error(e)
            level = log.error if code == "internal_error" else log.warning
            level(
                "run.failed",
                run_id=run.id,
                code=code,
                error=message,
                exc_info=code == "internal_error",
            )
        finally:
            # Await the cancelled heartbeat: it may be mid-write, and an un-awaited task
            # holding a connection blocks engine disposal / loop shutdown.
            await _cancel_and_wait(hb)

        async with self.db.session() as s:
            ok = await runs_repo.finish(
                s,
                run.id,
                worker_id,
                status=status,
                result=result,
                error_code=code,
                error_message=message,
            )
            audit_repo.add_event(
                s,
                event_type=f"run.{status.value}",
                run_id=run.id,
                subject_type=run.subject_type,
                subject_id=run.subject_id,
                payload={**result, "code": code, "message": message, "recorded": ok},
            )
