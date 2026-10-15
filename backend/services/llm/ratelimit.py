"""Process-wide LLM throttle: evenly spaced request starts (RPM) + a concurrency cap.

Spacing (rather than a bursty token bucket) keeps free-tier providers from tripping their
per-minute limits when a batch of runs starts at once. Every attempt, including retries,
passes through here.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager


class RateLimiter:
    def __init__(
        self,
        rpm: int,
        max_concurrency: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval = 60.0 / rpm if rpm > 0 else 0.0
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._lock = asyncio.Lock()
        self._next_start = 0.0
        self._clock = clock
        self._sleep = sleep

    async def _wait_turn(self) -> None:
        async with self._lock:
            now = self._clock()
            start = max(now, self._next_start)
            self._next_start = start + self.interval
        delay = start - now
        if delay > 0:
            await self._sleep(delay)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._sem:
            await self._wait_turn()
            yield
