from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.live.agent import AgentLoop
from app.live.echo_guard import EchoGuard
from app.live.models import LlmResponse, UserTextMessage
from app.live.session import LiveSessionContext
from app.packet.models import Sweep
from app.server.live_output import handle_user_turn as _handle_user_turn
from app.server.live_output import send_cue
from app.server.ws_live import _queue_final_text
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
    session = LiveSessionContext("sw_20261126_030042_1552", tmp_path, echo_guard=EchoGuard(6, 85))
    session.echo_guard.add_spoken_line("Please turn on a light")
    pending: list[str] = []

    _queue_final_text(
        session,
        UserTextMessage(type="user_text", text="Please turn on a light", t_ms=50),
        pending,
    )

    assert pending == []
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    event = next(event for event in events if event["type"] == "echo_dropped")
    assert event["type"] == "echo_dropped"
    assert event["payload"]["similarity"] >= 85


def test_echo_guard_ignores_nonmatch_and_expires_after_window() -> None:
    now = [0.0]
    guard = EchoGuard(6, 85, clock=lambda: now[0])
    guard.add_spoken_line("Turn on a light")

    assert guard.match("Tell me about this shelf") is None
    assert guard.match("Turn on a light") is not None
    now[0] = 6.1
    assert guard.match("Turn on a light") is None


def _write_sweep(tmp_path: Path) -> None:
    (tmp_path / "sweep.json").write_text(
        Sweep(
            id="sw_20261126_030042_1552",
            captured_at="2026-11-26T03:00:42+05:30",
            device="test",
            duration_s=0,
            country="IN",
            currency="INR",
            locale_config="config/locales/IN.yaml",
        ).model_dump_json(),
        encoding="utf-8",
    )


def _make_settings(tmp_path: Path) -> Settings:
    settings = Settings(config=YamlSettings(), sweeps_dir=tmp_path, _env_file=None)
    return settings


class _ScriptedClient:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self.responses = responses
        self.calls = 0

    async def generate(self, **_: object) -> LlmResponse:
        self.calls += 1
        return self.responses.pop(0)


async def test_stable_forced_interim_with_cue_echo_routes_locale_under_1_5s(
    tmp_path: Path,
) -> None:
    _write_sweep(tmp_path)
    session = LiveSessionContext("sw_20261126_030042_1552", tmp_path)
    session.echo_guard.add_spoken_line("Hold the phone steadier for a moment.")
    client = _ScriptedClient([])
    agent = AgentLoop(_make_settings(tmp_path), session, client)
    session.agent = agent
    pending: list[str] = []

    started = asyncio.get_running_loop().time()
    await asyncio.sleep(1.2)
    accepted = _queue_final_text(
        session,
        UserTextMessage(
            type="user_text",
            text="Hold the phone steadier for a moment yes I'm from India",
            t_ms=1200,
            forced_final=True,
        ),
        pending,
    )
    await _handle_user_turn(session, " ".join(pending))
    elapsed = asyncio.get_running_loop().time() - started

    assert accepted is True
    assert session.locale_confirmed is True
    assert client.calls == 0
    assert elapsed < 1.5
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    cleaned_event = next(event for event in events if event["type"] == "transcript_cleaned")
    assert cleaned_event["payload"]["original"].startswith("Hold the phone")
    assert cleaned_event["payload"]["cleaned"] == "yes I'm from India"
    assert any(
        event["type"] == "intent_routed" and event["payload"]["kind"] == "locale"
        for event in events
    )


def test_echo_filter_preserves_short_answers_and_drops_full_cue_repeat(tmp_path: Path) -> None:
    session = LiveSessionContext("sw_20261126_030042_1552", tmp_path, echo_guard=EchoGuard(6, 85))
    session.echo_guard.add_spoken_line("Move the phone more slowly, please.")
    for answer in ("yes", "India"):
        pending: list[str] = []
        assert _queue_final_text(
            session, UserTextMessage(type="user_text", text=answer, t_ms=2), pending
        )
        assert pending == [answer]

    pending = []
    assert not _queue_final_text(
        session,
        UserTextMessage(type="user_text", text="Move the phone more slowly please", t_ms=3),
        pending,
    )
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    dropped = [event for event in events if event["type"] == "echo_dropped"]
    assert dropped[-1]["payload"]["similarity"] >= 85


async def test_scripted_user_turns_get_one_reply_while_cues_are_blocked(tmp_path: Path) -> None:
    _write_sweep(tmp_path)
    responses = [LlmResponse(text="Yes, I can see the shelf.")]
    client = _ScriptedClient(responses)
    session = LiveSessionContext("sw_20261126_030042_1552", tmp_path, cue_suppress_after_user_s=0)
    session.agent = AgentLoop(_make_settings(tmp_path), session, client)
    socket = FakeWebSocket()
    session.websocket = socket

    for text in ("yes", "can you see the shelf now?", "that painting is a print", "I'm done"):
        session.agent_turn_pending = True
        assert not await send_cue(session, "Hold the phone steadily", kind="BLURRY")
        session.agent_turn_pending = False
        await _handle_user_turn(session, text)
        assert not await send_cue(session, "Move the phone slowly", kind="TOO_FAST")

    replies = [message for message in socket.sent if message.get("type") == "agent_text"]
    assert len(replies) == 4
    assert not any(message.get("type") == "cue" for message in socket.sent)
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len([event for event in events if event["type"] == "agent_reply"]) == 4
    assert len([event for event in events if event["type"] == "cue_suppressed"]) == 8


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
