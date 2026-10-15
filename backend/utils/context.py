"""Per-task context (run id / node) so deep layers like the LLM client can attribute audit rows
without threading ids through every call."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import structlog

current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)
current_node: ContextVar[str | None] = ContextVar("current_node", default=None)


@contextmanager
def run_context(run_id: str) -> Iterator[None]:
    token = current_run_id.set(run_id)
    with structlog.contextvars.bound_contextvars(run_id=run_id):
        try:
            yield
        finally:
            current_run_id.reset(token)


@contextmanager
def node_context(node: str) -> Iterator[None]:
    token = current_node.set(node)
    with structlog.contextvars.bound_contextvars(node=node):
        try:
            yield
        finally:
            current_node.reset(token)
