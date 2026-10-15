"""Anthropic Messages API via the official SDK.

- Structured output through ``output_config.format`` (JSON schema) — no forced tool_choice,
  which current models reject.
- No ``temperature``: current models reject non-default sampling values.
- SDK retries disabled (``max_retries=0``); our RetryPolicy owns retries and auditing.
- Server-side refusal fallback opted in on models that support it.
"""

from __future__ import annotations

from typing import Any

import anthropic

from backend.config import StructuredMode
from backend.services.llm.retry import parse_retry_after
from backend.services.llm.types import (
    ChatMessage,
    ProviderError,
    RawCompletion,
    is_retryable_status,
)

FALLBACK_MODELS = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        mode: StructuredMode,
        timeout_s: float,
        effort: str = "",
        fallbacks: bool = True,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.mode = mode
        self.effort = effort
        self.use_fallbacks = fallbacks and model in FALLBACK_MODELS
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key or None, timeout=timeout_s, max_retries=0
        )

    def build_kwargs(
        self,
        messages: list[ChatMessage],
        *,
        schema: dict[str, Any] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        output_config: dict[str, Any] = {}
        if self.effort:
            output_config["effort"] = self.effort
        if schema is not None and self.mode != "prompt":
            output_config["format"] = {"type": "json_schema", "schema": schema}
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": convo,
        }
        if system:
            kwargs["system"] = system
        if output_config:
            kwargs["output_config"] = output_config
        if self.use_fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        schema: dict[str, Any] | None,
        schema_name: str,
        temperature: float,
        max_tokens: int,
    ) -> RawCompletion:
        kwargs = self.build_kwargs(messages, schema=schema, max_tokens=max_tokens)
        try:
            resp = await self._client.beta.messages.create(**kwargs)
        except anthropic.APITimeoutError as e:
            raise ProviderError(f"timeout: {e}", retryable=True, code="timeout") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"connection: {e}", retryable=True, code="network") from e
        except anthropic.RateLimitError as e:
            raise ProviderError(
                f"rate limited: {e.message}",
                status=429,
                retryable=True,
                retry_after_s=parse_retry_after(e.response.headers),
                code="rate_limited",
            ) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(
                f"HTTP {e.status_code}: {e.message}",
                status=e.status_code,
                retryable=is_retryable_status(e.status_code),
                retry_after_s=parse_retry_after(e.response.headers),
                code=f"http_{e.status_code}",
            ) from e

        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            raise ProviderError(
                f"model refused (category={getattr(details, 'category', None)})",
                retryable=False,
                code="refusal",
            )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        if resp.stop_reason == "max_tokens" and not text.strip():
            raise ProviderError("hit max_tokens with no output", retryable=False, code="max_tokens")
        if not text.strip():
            raise ProviderError("empty completion", retryable=True, code="empty")
        usage = getattr(resp, "usage", None)
        return RawCompletion(
            text=text,
            model=getattr(resp, "model", self.model),
            http_status=200,
            prompt_tokens=getattr(usage, "input_tokens", None),
            completion_tokens=getattr(usage, "output_tokens", None),
            extra={
                "stop_reason": resp.stop_reason,
                "request_id": getattr(resp, "_request_id", None),
            },
        )

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()
