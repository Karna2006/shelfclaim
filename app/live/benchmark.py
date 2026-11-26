"""Measure one configured text generation call for each Gemini model.

Input: app settings and the model client interface. Output: per-model latency
and a safe success/error result for the `check-llm` developer command.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.live.client import GeminiFlashClient, LlmClient
from app.live.models import AgentMessage
from app.live.rate_limit import ModelRateLimiter
from app.settings import Settings


@dataclass(frozen=True)
class BenchmarkResult:
    model: str
    latency_s: float
    ok: bool
    error_type: str | None = None
    response_text: str | None = None


async def benchmark_models(
    settings: Settings,
    client: LlmClient | None = None,
) -> list[BenchmarkResult]:
    """Run one bounded `Say OK` request through each configured model."""
    selected = client or GeminiFlashClient(settings, ModelRateLimiter(settings.config.llm))
    results: list[BenchmarkResult] = []
    try:
        for model, thinking in ((settings.agent_model, "minimal"), (settings.vision_model, None)):
            started = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    selected.generate(
                        model=model,
                        system_prompt="Reply briefly to the user's request.",
                        history=[AgentMessage(role="user", text="Say OK")],
                        tools=[],
                        thinking_level=thinking,
                        timeout_s=settings.config.agent.timeout_s,
                    ),
                    timeout=settings.config.agent.timeout_s,
                )
                results.append(
                    BenchmarkResult(
                        model=model,
                        latency_s=time.perf_counter() - started,
                        ok=True,
                        response_text=response.text,
                    )
                )
            except Exception as exc:
                results.append(
                    BenchmarkResult(
                        model=model,
                        latency_s=time.perf_counter() - started,
                        ok=False,
                        error_type=type(exc).__name__,
                    )
                )
    finally:
        close = getattr(selected, "close", None)
        if close is not None:
            await close()
    return results
