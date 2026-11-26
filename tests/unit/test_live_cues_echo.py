from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.live.agent import AgentLoop
from app.live.echo_guard import EchoGuard
from app.live.models import LlmResponse, UserTextMessage
from app.live.session import LiveSessionContext
from app.server.ws_live import _handle_user_turn, _queue_final_text, send_cue
from app.settings import Settings, YamlSettings


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, message: dict[str, object]) -> None:
        self.sent.append(message)


async def test_cue_message_is_sent_and_logged_as_spoken_history(tmp_path: Path) -> None:
    session = LiveSessionContext("sw_20261126_030042_1552", tmp_path)

    class AgentNote:
        def __init__(self) -> None:
            self.notes: list[str] = []

        def record_cue(self, text: str) -> None:
            self.notes.append(text)

    agent_note = AgentNote()
    session.agent = agent_note
    socket = FakeWebSocket()
    session.websocket = socket
    await send_cue(session, "Turn on a light", priority=20)

    assert socket.sent == [{"type": "cue", "text": "Turn on a light", "priority": 20}]
    assert session.echo_guard.match("Turn on a light") is not None
    assert agent_note.notes == ["Turn on a light"]
    transcript = json.loads((tmp_path / "transcript.jsonl").read_text(encoding="utf-8"))
    assert transcript["speaker"] == "cue"


def test_echo_guard_drops_recent_spoken_lines(tmp_path: Path) -> None:
    session = LiveSessionContext("sw_20261126_030042_1552", tmp_path, echo_guard=EchoGuard(10, 85))
    session.echo_guard.add_spoken_line("Please turn on a light")
    pending: list[str] = []

    _queue_final_text(
        session,
        UserTextMessage(type="user_text", text="Please turn on light", t_ms=50),
        pending,
    )

    assert pending == []
    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))
    assert event["type"] == "echo_dropped"
    assert event["payload"]["similarity"] >= 85


def test_echo_guard_ignores_nonmatch_and_expires_after_window() -> None:
    now = [0.0]
    guard = EchoGuard(10, 85, clock=lambda: now[0])
    guard.add_spoken_line("Turn on a light")

    assert guard.match("Tell me about this shelf") is None
    assert guard.match("Turn on a light") is not None
    now[0] = 10.1
    assert guard.match("Turn on a light") is None


async def test_slow_turn_speaks_one_moment_then_real_reply(tmp_path: Path) -> None:
    class SlowClient:
        async def generate(self, **_: object) -> LlmResponse:
            await asyncio.sleep(0.03)
            return LlmResponse(text="I can help with the shelf.")

    settings = Settings(config=YamlSettings(), _env_file=None)
    agent_settings = settings.config.agent.model_copy(
        update={
            "filler_after_s": 0.01,
            "model_chain": ["gemini-3.1-flash-lite"],
            "retry_backoff_s": [],
        }
    )
    config = settings.config.model_copy(update={"agent": agent_settings})
    settings = settings.model_copy(update={"config": config})
    context = LiveSessionContext("sw_20261126_030042_1552", tmp_path)
    context.agent = AgentLoop(settings, context, SlowClient())
    socket = FakeWebSocket()
    context.websocket = socket

    await _handle_user_turn(context, "Please tell me about the room")

    assert [message["text"] for message in socket.sent if message["type"] == "agent_text"] == [
        "One moment.",
        "I can help with the shelf.",
    ]
    transcript = [
        json.loads(line)
        for line in (tmp_path / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [line["text"] for line in transcript if line["speaker"] == "agent"] == [
        "One moment.",
        "I can help with the shelf.",
    ]
