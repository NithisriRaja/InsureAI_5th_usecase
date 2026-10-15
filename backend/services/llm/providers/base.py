from __future__ import annotations

from typing import Any, Protocol

from backend.services.llm.types import ChatMessage, RawCompletion


class Provider(Protocol):
    name: str
    model: str

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        schema: dict[str, Any] | None,
        schema_name: str,
        temperature: float,
        max_tokens: int,
    ) -> RawCompletion:
        """One HTTP call. Raises ProviderError (classified) on failure.

        ``schema`` is set only when the provider should enforce JSON natively; prompt-mode
        callers embed the schema in the messages instead.
        """
        ...

    async def aclose(self) -> None: ...
