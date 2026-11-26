from __future__ import annotations

import json
from pathlib import Path

from app.live.echo_guard import EchoGuard
from app.live.models import UserTextMessage
from app.live.session import LiveSessionContext
from app.server.ws_live import _queue_final_text, send_cue


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
