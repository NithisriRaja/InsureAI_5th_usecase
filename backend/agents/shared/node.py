from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableConfig

from backend.agents.state import GraphState
from backend.utils.context import node_context


class SubjectNotFound(LookupError):
    code = "subject_not_found"


NodeFn = Callable[[GraphState, RunnableConfig], Awaitable[dict[str, Any]]]


def node(name: str) -> Callable[[NodeFn], NodeFn]:
    """Bind the node name into logging/audit context for everything the node does."""

    def wrap(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def inner(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
            with node_context(name):
                return await fn(state, config)

        return inner

    return wrap


BAND_PRIORITY = {
    "high": "high",
    "medium": "medium",
    "low": "low",
}
