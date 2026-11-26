from __future__ import annotations

from app.live.rate_limit import ModelRateLimiter
from app.settings import LlmSettings, ModelRateLimitSettings


def test_model_overrides_and_retry_backoff_are_configurable() -> None:
    settings = LlmSettings(
        default_rate_limit=ModelRateLimitSettings(requests_per_minute=2),
        model_rate_limits={
            "agent": ModelRateLimitSettings(
                requests_per_minute=8,
                backoff_initial_s=0.25,
                backoff_max_s=3,
            )
        },
    )
    limiter = ModelRateLimiter(settings)

    assert limiter.settings_for("agent").requests_per_minute == 8
    assert limiter.settings_for("vision").requests_per_minute == 2
    assert limiter.backoff_s("agent", 2) == 1
    assert limiter.backoff_s("agent", 2, retry_after_s=2) == 2


async def test_acquire_waits_then_expires_old_request() -> None:
    now = [0.0]
    waits: list[float] = []

    async def advance(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    settings = LlmSettings(
        default_rate_limit=ModelRateLimitSettings(requests_per_minute=1, window_s=5)
    )
    limiter = ModelRateLimiter(settings, clock=lambda: now[0], sleep=advance)

    await limiter.acquire("agent")
    await limiter.acquire("agent")

    assert waits == [5]
    assert now[0] == 5
