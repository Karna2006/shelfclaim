"""Retry transient live-model failures and record request diagnostics.

Input: one current AgentLoop prompt and configured model chain. Output: the
first successful model response; images are retried without image data only
after the complete configured chain fails.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.live.client import LlmClient
from app.live.models import AgentMessage, LlmResponse, ToolSchema
from app.pipeline.artifacts import Event
from app.settings import Settings
from app.telemetry.events import write_event


async def generate_with_fallback(
    client: LlmClient,
    settings: Settings,
    sweep_dir: Path,
    t_ms: int,
    system_prompt: str,
    history: list[AgentMessage],
    tools: list[ToolSchema],
    max_output_tokens: int,
) -> tuple[LlmResponse, str]:
    """Try transient retries, configured models, then one image-free pass."""
    models = list(dict.fromkeys([settings.agent_model, *settings.config.agent.model_chain]))
    try:
        return await _try_chain(
            client,
            settings,
            sweep_dir,
            t_ms,
            models,
            system_prompt,
            history,
            tools,
            max_output_tokens,
        )
    except Exception as first_error:
        if not any(message.image_jpeg is not None for message in history):
            raise
        write_event(
            sweep_dir,
            Event(
                t_ms=t_ms,
                type="agent_attempt",
                payload={
                    "phase": "retry_without_image",
                    "error_type": type(first_error).__name__,
                    "error_message": str(first_error),
                },
            ),
        )
        without_images = [message.model_copy(update={"image_jpeg": None}) for message in history]
        return await _try_chain(
            client,
            settings,
            sweep_dir,
            t_ms,
            models,
            system_prompt,
            without_images,
            tools,
            max_output_tokens,
        )


async def _try_chain(
    client: LlmClient,
    settings: Settings,
    sweep_dir: Path,
    t_ms: int,
    models: list[str],
    system_prompt: str,
    history: list[AgentMessage],
    tools: list[ToolSchema],
    max_output_tokens: int,
) -> tuple[LlmResponse, str]:
    backoffs = settings.config.agent.retry_backoff_s
    failures: list[Exception] = []
    for model in models:
        for attempt in range(len(backoffs) + 1):
            shape = _request_shape(history, system_prompt, len(tools))
            write_event(
                sweep_dir,
                Event(t_ms=t_ms, type="agent_request", payload={"model": model, **shape}),
            )
            started = time.perf_counter()
            try:
                response = await client.generate(
                    model=model,
                    system_prompt=system_prompt,
                    history=history,
                    tools=tools,
                    thinking_level="minimal",
                    timeout_s=settings.config.agent.timeout_s,
                    max_output_tokens=max_output_tokens,
                )
            except Exception as exc:
                failures.append(exc)
                write_event(
                    sweep_dir,
                    Event(
                        t_ms=t_ms,
                        type="agent_attempt",
                        payload={
                            "model": model,
                            "attempt": attempt + 1,
                            "latency_ms": round((time.perf_counter() - started) * 1000),
                            "success": False,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            **shape,
                        },
                    ),
                )
                if not _is_transient_error(exc):
                    raise
                if attempt < len(backoffs):
                    await asyncio.sleep(backoffs[attempt])
                continue
            usage = response.diagnostics.get("usage_metadata")
            exact_tokens = usage.get("prompt_token_count") if isinstance(usage, dict) else None
            write_event(
                sweep_dir,
                Event(
                    t_ms=t_ms,
                    type="agent_attempt",
                    payload={
                        "model": model,
                        "attempt": attempt + 1,
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                        "success": True,
                        "error": None,
                        **shape,
                        "total_prompt_tokens": exact_tokens,
                    },
                ),
            )
            return response, model
    if failures:
        raise failures[-1]
    raise RuntimeError("No agent model configured")


def _request_shape(
    history: list[AgentMessage], system_prompt: str, tool_count: int
) -> dict[str, int | None]:
    """Describe request size while avoiding frame contents and credentials."""
    images = [message for message in history if message.image_jpeg is not None]
    text = system_prompt + " " + " ".join(message.text or "" for message in history)
    structured = " ".join(
        json.dumps(
            {
                "calls": [
                    call.model_dump(exclude={"thought_signature"}) for call in message.tool_calls
                ],
                "results": [result.model_dump() for result in message.tool_results],
            },
            ensure_ascii=False,
        )
        for message in history
    )
    return {
        "history_messages": len(history),
        "history_turns": sum(
            1 for message in history if message.role == "user" and not message.tool_results
        ),
        "image_parts": len(images),
        "image_bytes": sum(len(message.image_jpeg or b"") for message in images),
        "tool_count": tool_count,
        "estimated_prompt_tokens": max(1, (len(text) + len(structured)) // 4 + 258 * len(images)),
        "total_prompt_tokens": None,
    }


def _is_transient_error(error: Exception) -> bool:
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    if status in {500, 503, 504} or isinstance(error, TimeoutError):
        return True
    message = str(error).upper()
    return any(
        marker in message
        for marker in ("500", "503", "504", "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED")
    )
