"""Domo AI Services text generation over httpx.

``POST {base}/ai/v1/text/generation`` with ``{"input", "system", "model"}``; auth via the
``X-DOMO-Developer-Token`` header. The endpoint is single-turn, so a multi-turn conversation
(the client's repair round) is flattened into one ``input`` with role-labelled sections.
There is no native JSON-schema mode: the schema always travels in the system prompt.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.config import StructuredMode
from backend.services.llm.retry import parse_retry_after
from backend.services.llm.types import (
    ChatMessage,
    ProviderError,
    RawCompletion,
    is_retryable_status,
)

TEXT_PATH = "/ai/v1/text/generation"


class DomoProvider:
    name = "domo"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        mode: StructuredMode,
        timeout_s: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.mode = mode
        self._url = base_url.rstrip("/") + TEXT_PATH
        headers = {
            "X-DOMO-Developer-Token": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._client = client or httpx.AsyncClient(timeout=timeout_s, headers=headers)
        if client is not None:
            self._client.headers.update(headers)

    def build_body(self, messages: list[ChatMessage]) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [m for m in messages if m.role != "system"]
        if len(convo) == 1 and convo[0].role == "user":
            text = convo[0].content
        else:
            label = {"user": "USER", "assistant": "YOUR PREVIOUS REPLY"}
            text = "\n\n".join(f"### {label[m.role]}\n{m.content}" for m in convo)
        body: dict[str, Any] = {"input": text, "model": self.model}
        if system:
            body["system"] = system
        return body

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        schema: dict[str, Any] | None,
        schema_name: str,
        temperature: float,
        max_tokens: int,
    ) -> RawCompletion:
        try:
            resp = await self._client.post(self._url, json=self.build_body(messages))
        except httpx.TimeoutException as e:
            raise ProviderError(f"timeout: {e}", retryable=True, code="timeout") from e
        except httpx.TransportError as e:
            raise ProviderError(f"transport: {e}", retryable=True, code="network") from e

        if resp.status_code >= 400:
            raise ProviderError(
                f"HTTP {resp.status_code}: {resp.text[:500]}",
                status=resp.status_code,
                retryable=is_retryable_status(resp.status_code),
                retry_after_s=parse_retry_after(resp.headers),
                code="rate_limited" if resp.status_code == 429 else f"http_{resp.status_code}",
            )
        try:
            data = resp.json()
        except ValueError as e:
            raise ProviderError(
                "non-JSON response body", status=resp.status_code, retryable=True, code="bad_body"
            ) from e
        if not isinstance(data, dict):
            raise ProviderError(
                "malformed completion", status=resp.status_code, retryable=True, code="bad_body"
            )

        text = data.get("output")
        if text is None:
            choices = data.get("choices") or []
            text = choices[0].get("output") if choices and isinstance(choices[0], dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(
                "empty completion", status=resp.status_code, retryable=True, code="empty"
            )
        usage = data.get("modelProviderUsage") or {}
        return RawCompletion(
            text=text,
            model=data.get("modelId") or self.model,
            http_status=resp.status_code,
            prompt_tokens=usage.get("inputTokens"),
            completion_tokens=usage.get("outputTokens"),
            extra={"request_id": data.get("requestId")},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
