"""Scripted provider for tests. Never used as a production fallback.

``responder(purpose, messages)`` returns a dict (serialised to JSON), a raw string, or raises
ProviderError. Purpose is read from the first line of the system prompt ("PURPOSE: x").
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.services.llm.types import ChatMessage, ProviderError, RawCompletion

Responder = Callable[[str, list[ChatMessage]], Any]


def purpose_of(messages: list[ChatMessage]) -> str:
    for m in messages:
        if m.role == "system" and m.content.startswith("PURPOSE: "):
            return m.content.split("\n", 1)[0].removeprefix("PURPOSE: ").strip()
    return ""


class FakeProvider:
    name = "fake"

    def __init__(self, responder: Responder | None = None, model: str = "fake-model") -> None:
        self.model = model
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        schema: dict[str, Any] | None,
        schema_name: str,
        temperature: float,
        max_tokens: int,
    ) -> RawCompletion:
        purpose = purpose_of(messages)
        self.calls.append({"purpose": purpose, "messages": messages, "schema": schema})
        if self.responder is None:
            raise ProviderError(
                "FakeProvider has no responder", retryable=False, code="not_configured"
            )
        out = self.responder(purpose, messages)
        text = out if isinstance(out, str) else json.dumps(out)
        return RawCompletion(text=text, model=self.model, prompt_tokens=10, completion_tokens=10)

    async def aclose(self) -> None:
        return None
