"""Provide a testable asynchronous client for Gemini Flash function calling.

Input is typed conversation history and function declarations; output is text
and normalized tool calls. Implements `docs/04_ARCHITECTURE.md` §5.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from app.live.models import AgentMessage, LlmResponse, LlmToolCall, ToolSchema
from app.live.rate_limit import ModelRateLimiter
from app.settings import Settings
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class LlmClient(Protocol):
    async def generate(
        self,
        *,
        model: str,
        system_prompt: str,
        history: list[AgentMessage],
        tools: list[ToolSchema],
        thinking_level: str | None,
        timeout_s: float,
        max_output_tokens: int = 1024,
    ) -> LlmResponse: ...


class GeminiFlashClient:
    """Call the async Google Gen AI SDK with app-level pacing and 429 backoff."""

    def __init__(self, settings: Settings, limiter: ModelRateLimiter) -> None:
        if settings.google_api_key is None:
            raise ValueError("GOOGLE_API_KEY is required for the agent brain")
        self._limiter = limiter
        self._client = genai.Client(
            api_key=settings.google_api_key.get_secret_value(),
            http_options=types.HttpOptions(
                timeout=round(settings.config.agent.timeout_s * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self._async_client = self._client.aio

    async def generate(
        self,
        *,
        model: str,
        system_prompt: str,
        history: list[AgentMessage],
        tools: list[ToolSchema],
        thinking_level: str | None,
        timeout_s: float,
        max_output_tokens: int = 1024,
    ) -> LlmResponse:
        """Generate one model turn, retrying only rate-limit responses."""
        rate = self._limiter.settings_for(model)
        deadline = asyncio.get_running_loop().time() + timeout_s
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters,
            )
            for tool in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            max_output_tokens=max_output_tokens,
            thinking_config=(
                types.ThinkingConfig(thinking_level=thinking_level)
                if thinking_level is not None
                else None
            ),
        )
        contents = [_to_genai_content(message) for message in history]

        for attempt in range(rate.max_retries + 1):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Agent model {model} exceeded its {timeout_s:g}s deadline")
            await asyncio.wait_for(self._limiter.acquire(model), timeout=remaining)
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                async with asyncio.timeout(remaining):
                    response = await self._async_client.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                diagnostics = _response_diagnostics(response)
                logger.info("Agent response diagnostics model=%s %s", model, diagnostics)
                return _normalize_response(response, diagnostics)
            except Exception as exc:
                if not _is_rate_limit_error(exc) or attempt >= rate.max_retries:
                    raise
                delay = self._limiter.backoff_s(model, attempt, _retry_after_seconds(exc))
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0 or delay >= remaining:
                    raise TimeoutError(
                        f"Agent model {model} exceeded its {timeout_s:g}s deadline"
                    ) from exc
                logger.info(
                    "Gemini rate limited model=%s; retry=%d delay_s=%.2f", model, attempt + 1, delay
                )
                await asyncio.sleep(delay)
        raise RuntimeError("LLM retry loop exited without a response")

    async def close(self) -> None:
        """Close the async SDK transport when its app session is disposed."""
        await self._async_client.aclose()
        self._client.close()


def _to_genai_content(message: AgentMessage) -> types.Content:
    parts: list[types.Part] = []
    if message.text:
        parts.append(types.Part(text=message.text))
    if message.image_jpeg is not None:
        parts.append(types.Part.from_bytes(data=message.image_jpeg, mime_type="image/jpeg"))
    for call in message.tool_calls:
        parts.append(
            types.Part(
                function_call=types.FunctionCall(
                    name=call.name, args=call.arguments, id=call.call_id
                ),
                thought_signature=call.thought_signature,
            )
        )
    for result in message.tool_results:
        response_fields: dict[str, object] = {
            "name": result.name,
            "response": result.response,
        }
        if result.call_id and "id" in types.FunctionResponse.model_fields:
            response_fields["id"] = result.call_id
        parts.append(types.Part(function_response=types.FunctionResponse(**response_fields)))
    return types.Content(role=message.role, parts=parts)


def _normalize_response(
    response: types.GenerateContentResponse,
    diagnostics: dict[str, object] | None = None,
) -> LlmResponse:
    parts = _response_parts(response)
    text_parts: list[str] = []
    calls: list[LlmToolCall] = []
    for part in parts or []:
        if part.text:
            text_parts.append(part.text)
        if part.function_call is not None:
            function_call = part.function_call
            calls.append(
                LlmToolCall(
                    name=function_call.name or "",
                    arguments=dict(function_call.args or {}),
                    call_id=function_call.id,
                    thought_signature=part.thought_signature,
                )
            )
    response_text = "".join(text_parts).strip() or None
    return LlmResponse(text=response_text, tool_calls=calls, diagnostics=diagnostics or {})


def _response_diagnostics(response: types.GenerateContentResponse) -> dict[str, object]:
    """Capture model termination, token usage, prompt feedback, and returned part types."""
    candidate = response.candidates[0] if response.candidates else None
    parts = _response_parts(response)
    usage = response.usage_metadata
    feedback = response.prompt_feedback
    usage_payload = usage.model_dump(mode="json", exclude_none=True) if usage else None
    if usage_payload is not None:
        usage_payload["thoughts_token_count"] = usage.thoughts_token_count
        usage_payload["candidates_token_count"] = usage.candidates_token_count
    prompt_feedback = feedback.model_dump(mode="json", exclude_none=True) if feedback else None
    block_reason = _enum_name(feedback.block_reason) if feedback else None
    return {
        "finish_reason": _enum_name(candidate.finish_reason) if candidate else None,
        "usage_metadata": usage_payload,
        "prompt_feedback": prompt_feedback,
        "block_reason": block_reason,
        "has_text_part": any(part.text is not None for part in parts),
        "has_function_call_part": any(part.function_call is not None for part in parts),
    }


def _response_parts(response: types.GenerateContentResponse) -> list[types.Part]:
    if not response.candidates or response.candidates[0].content is None:
        return []
    return response.candidates[0].content.parts or []


def _enum_name(value: object | None) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "name", value))


def _is_rate_limit_error(error: Exception) -> bool:
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    return status == 429 or "429" in str(error)


def _retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    value = headers.get("retry-after") if headers else None
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None
