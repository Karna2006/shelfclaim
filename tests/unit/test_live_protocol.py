from __future__ import annotations

import base64
import json

import pytest
from app.live.models import (
    LiveFrameMessage,
    SpeechActivityMessage,
    SpeechEventMessage,
    UserTextMessage,
    parse_live_message,
)


def test_parse_final_text_protocol() -> None:
    message = parse_live_message(json.dumps({"type": "user_text", "text": "Hello", "t_ms": 12}))
    assert isinstance(message, UserTextMessage)
    assert message.text == "Hello"


def test_parse_speech_activity_protocol() -> None:
    message = parse_live_message(json.dumps({"type": "speech_activity", "speaking": True}))
    assert isinstance(message, SpeechActivityMessage)
    assert message.speaking is True


def test_parse_speech_event_protocol() -> None:
    message = parse_live_message(
        json.dumps({"type": "speech_event", "name": "onerror", "detail": "no-speech", "t_ms": 35})
    )
    assert isinstance(message, SpeechEventMessage)
    assert message.name == "onerror"
    assert message.detail == "no-speech"


def test_parse_low_resolution_frame_protocol() -> None:
    payload = base64.b64encode(b"\xff\xd8jpeg bytes").decode("ascii")
    message = parse_live_message(json.dumps({"type": "live_frame", "data": payload, "t_ms": 3}))
    assert isinstance(message, LiveFrameMessage)
    assert message.jpeg_bytes() == b"\xff\xd8jpeg bytes"


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "audio", "data": "raw audio"},
        {"type": "interim", "text": "partial", "t_ms": 1},
        {"type": "user_text", "text": "ok", "t_ms": 1, "interim": True},
        {"type": "live_frame", "data": "not base64!", "t_ms": 1},
    ],
)
def test_reject_unsupported_or_invalid_live_protocol(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Invalid /ws/live message"):
        parse_live_message(json.dumps(payload))
