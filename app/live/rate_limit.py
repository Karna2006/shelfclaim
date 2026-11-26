"""Apply per-model request pacing and retry delays for free-tier quotas.

Input is a model name and validated YAML settings; output is permission to
request or a bounded backoff duration. Implements `docs/03_TECH_STACK.md` §7.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from app.settings import LlmSettings, ModelRateLimitSettings


class ModelRateLimiter:
    """A process-local sliding-window limiter keyed by exact model ID."""

    def __init__(
        self,
        settings: LlmSettings,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._sleep = sleep
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def acquire(self, model: str) -> None:
        """Wait until this model has room in its configured rolling window."""
        limit = self.settings_for(model)
        while True:
            async with self._locks[model]:
                now = self._clock()
                requests = self._requests[model]
                while requests and now - requests[0] >= limit.window_s:
                    requests.popleft()
                if len(requests) < limit.requests_per_minute:
                    requests.append(now)
                    return
                wait_s = max(0.0, requests[0] + limit.window_s - now)
            await self._sleep(wait_s)

    def settings_for(self, model: str) -> ModelRateLimitSettings:
        """Return the model override or conservative default settings."""
        return self._settings.model_rate_limits.get(model, self._settings.default_rate_limit)

    def backoff_s(self, model: str, attempt: int, retry_after_s: float | None = None) -> float:
        """Return the configured exponential delay, honoring bounded Retry-After."""
        settings = self.settings_for(model)
        exponential = settings.backoff_initial_s * (2**attempt)
        selected = max(exponential, retry_after_s or 0.0)
        return min(selected, settings.backoff_max_s)
