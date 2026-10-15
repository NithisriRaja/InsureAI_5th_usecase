"""Retry with exponential backoff + full jitter, honouring Retry-After, within a total budget."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import TypeVar

from backend.services.llm.types import ProviderError

T = TypeVar("T")


def parse_retry_after(headers: dict[str, str] | object) -> float | None:
    """Seconds to wait from Retry-After (seconds or HTTP date) or OpenRouter X-RateLimit-Reset
    (epoch milliseconds). None if absent/unparseable."""
    get = getattr(headers, "get", None)
    if get is None:
        return None
    value = get("retry-after") or get("Retry-After")
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError):
                pass
    reset = get("x-ratelimit-reset") or get("X-RateLimit-Reset")
    if reset:
        try:
            return max(0.0, float(reset) / 1000.0 - time.time())
        except ValueError:
            return None
    return None


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    max_total_wait_s: float = 120.0
    base_s: float = 1.0
    cap_s: float = 30.0
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep)
    rng: random.Random = field(default_factory=random.Random)

    def backoff(self, attempt: int) -> float:
        """Full jitter: uniform(0, min(cap, base * 2**(attempt-1)))."""
        return self.rng.uniform(0, min(self.cap_s, self.base_s * 2 ** (attempt - 1)))

    async def run(
        self,
        fn: Callable[[int], Awaitable[T]],
        on_retry: Callable[[int, ProviderError, float], None] | None = None,
    ) -> T:
        """Call ``fn(attempt)`` until success. Re-raises the last ProviderError when attempts
        or the wait budget run out, or immediately for non-retryable errors."""
        waited = 0.0
        attempt = 0
        while True:
            attempt += 1
            try:
                return await fn(attempt)
            except ProviderError as e:
                if not e.retryable or attempt >= self.max_attempts:
                    raise
                delay = e.retry_after_s if e.retry_after_s is not None else self.backoff(attempt)
                if waited + delay > self.max_total_wait_s:
                    e.code = "retry_budget_exhausted" if e.code == "provider_error" else e.code
                    raise
                if on_retry:
                    on_retry(attempt, e, delay)
                await self.sleep(delay)
                waited += delay
