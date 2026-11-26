from __future__ import annotations

from app.live.client import _normalize_response, _response_diagnostics, _to_genai_content
from app.live.models import AgentMessage, LlmToolCall, LlmToolResult
from google.genai import types


def test_history_converts_to_real_genai_types_without_network() -> None:
    messages = [
        AgentMessage(role="user", text="Hello"),
        AgentMessage(role="user", text="What is this?", image_jpeg=b"jpeg-bytes"),
        AgentMessage(
            role="model",
            tool_calls=[
                LlmToolCall(
                    name="set_locale",
                    arguments={"country": "IN"},
                    call_id="c-1",
                    thought_signature=b"opaque-signature",
                )
            ],
        ),
        AgentMessage(
            role="user",
            tool_results=[
                LlmToolResult(name="set_locale", response={"supported": True}, call_id="c-1")
            ],
        ),
        AgentMessage(role="model", text="Great, start at the left shelf."),
    ]

    contents = [_to_genai_content(message) for message in messages]

    assert all(isinstance(content, types.Content) for content in contents)
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "Hello"
    assert contents[1].parts[0].text == "What is this?"
    assert contents[1].parts[1].inline_data.data == b"jpeg-bytes"
    assert contents[2].role == "model"
    assert contents[2].parts[0].function_call.name == "set_locale"
    assert contents[2].parts[0].function_call.id == "c-1"
    assert contents[2].parts[0].thought_signature == b"opaque-signature"
    response = contents[3].parts[0].function_response
    assert response.name == "set_locale"
    assert response.response == {"supported": True}
    if "id" in types.FunctionResponse.model_fields:
        assert response.id == "c-1"
    assert contents[4].parts[0].text == "Great, start at the left shelf."


def test_normalized_function_call_keeps_the_sdk_thought_signature() -> None:
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="get_sweep_status", args={}, id="call-1"
                            ),
                            thought_signature=b"signed-call",
                        )
                    ],
                )
            )
        ]
    )

    normalized = _normalize_response(response)

    assert normalized.tool_calls[0].thought_signature == b"signed-call"


def test_response_diagnostics_capture_empty_max_tokens_and_usage() -> None:
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[]),
                finish_reason=types.FinishReason.MAX_TOKENS,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1487,
            thoughts_token_count=77,
            candidates_token_count=None,
            total_token_count=1564,
        ),
    )

    diagnostics = _response_diagnostics(response)

    assert diagnostics["finish_reason"] == "MAX_TOKENS"
    assert diagnostics["has_text_part"] is False
    assert diagnostics["has_function_call_part"] is False
    usage = diagnostics["usage_metadata"]
    assert usage["thoughts_token_count"] == 77
    assert usage["candidates_token_count"] is None
    assert diagnostics["block_reason"] is None
