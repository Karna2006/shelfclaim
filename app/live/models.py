"""Validated messages and model turns for the live voice cascade.

Input is `/ws/live` JSON or normalized model output; output is typed messages
shared by the WebSocket, agent, and Gemini client layers.
"""

from __future__ import annotations

import base64
import binascii
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class ClientMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserTextMessage(ClientMessage):
    type: Literal["user_text"]
    text: str = Field(min_length=1, max_length=4000)
    t_ms: int = Field(ge=0)


class LiveFrameMessage(ClientMessage):
    type: Literal["live_frame"]
    data: str = Field(min_length=1, max_length=1_000_000)
    t_ms: int = Field(ge=0)

    def jpeg_bytes(self) -> bytes:
        try:
            image = base64.b64decode(self.data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("live_frame data must be valid base64") from exc
        if not image.startswith(b"\xff\xd8"):
            raise ValueError("live_frame data must contain a JPEG")
        return image


class ControlMessage(ClientMessage):
    type: Literal["control"]
    action: Literal["stop"]


class SpeechActivityMessage(ClientMessage):
    type: Literal["speech_activity"]
    speaking: bool


LiveClientMessage = Annotated[
    UserTextMessage | LiveFrameMessage | ControlMessage | SpeechActivityMessage,
    Field(discriminator="type"),
]
_LIVE_MESSAGE_ADAPTER = TypeAdapter(LiveClientMessage)


def parse_live_message(
    raw: str,
) -> UserTextMessage | LiveFrameMessage | ControlMessage | SpeechActivityMessage:
    """Parse a supported client message; reject audio and interim-result payloads."""
    try:
        message = _LIVE_MESSAGE_ADAPTER.validate_json(raw)
        if isinstance(message, LiveFrameMessage):
            message.jpeg_bytes()
        return message
    except (ValidationError, ValueError) as exc:
        raise ValueError("Invalid /ws/live message") from exc


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, object]


class LlmToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    call_id: str | None = None
    thought_signature: bytes | None = None


class LlmToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    response: dict[str, object]
    call_id: str | None = None


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "model"]
    text: str | None = None
    image_jpeg: bytes | None = None
    tool_calls: list[LlmToolCall] = Field(default_factory=list)
    tool_results: list[LlmToolResult] = Field(default_factory=list)


class LlmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    tool_calls: list[LlmToolCall] = Field(default_factory=list)
    diagnostics: dict[str, object] = Field(default_factory=dict)


class AgentReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    stop_capture: bool = False
    start_sweep_after_reply: bool = False
