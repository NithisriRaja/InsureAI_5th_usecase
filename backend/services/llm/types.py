from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    content: str


@dataclass
class RawCompletion:
    text: str
    model: str
    http_status: int | None = 200
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """Transport/API error from a provider, classified for the retry policy."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool,
        retry_after_s: float | None = None,
        code: str = "provider_error",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after_s = retry_after_s
        self.code = code


RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529})


def is_retryable_status(status: int | None) -> bool:
    return status is None or status in RETRYABLE_STATUS or (status is not None and status >= 500)


class LLMError(Exception):
    """Raised to callers (graph nodes). ``code`` lands on the failed run."""

    code = "llm_error"

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMInvalidOutput(LLMError):
    code = "llm_invalid_output"


class LLMRefusal(LLMError):
    code = "llm_refusal"
