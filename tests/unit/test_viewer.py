"""Viewer state and report routes for docs/06 and the demo dashboard."""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.live.models import AgentReply
from app.live.session import LiveSessionContext
from app.server.live_output import send_reply
from app.server.main import create_app
from app.server.pages import report_path
from app.server.viewer import ViewerHub
from app.settings import Settings
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_viewer_receives_simulated_session_events() -> None:
    hub = ViewerHub()
    queue, initial = hub.attach("sw_20261127_120000_ab12")
    assert initial["type"] == "snapshot"

    for message in (
        {"type": "frame", "jpeg": "encoded"},
        {"type": "caption", "speaker": "user", "text": "Yes, India."},
        {"type": "inventory", "rows": [{"row": "A-1", "count": 8}], "items": []},
    ):
        await hub.publish("sw_20261127_120000_ab12", message)

    assert [queue.get_nowait()["type"] for _ in range(3)] == [
        "frame",
        "caption",
        "inventory",
    ]
    snapshot = hub.snapshot("sw_20261127_120000_ab12")
    assert snapshot["frame"]["jpeg"] == "encoded"
    assert snapshot["captions"][0]["text"] == "Yes, India."
    assert snapshot["inventory"]["rows"][0]["count"] == 8


@pytest.mark.asyncio
async def test_end_sweep_runs_shared_pipeline_in_worker_and_publishes_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import app.pipeline.orchestrator as orchestrator

    sweep_id = "sw_20261127_120000_ab12"
    sweep_dir = tmp_path / sweep_id
    sweep_dir.mkdir()
    settings = Settings(_env_file=None, sweeps_dir=tmp_path)
    socket = _FakeSocket(settings)
    hub = ViewerHub()
    context = LiveSessionContext(sweep_id, sweep_dir, viewer_hub=hub, websocket=socket)
    context.agent = SimpleNamespace(
        tools=SimpleNamespace(execute=_packet_summary),
        record_cue=lambda _text: None,
    )
    runner_threads: list[int] = []

    async def fake_run_pipeline(
        path: Path,
        _settings: Settings,
        *,
        on_progress: Callable[[dict[str, object]], Awaitable[None]],
    ) -> Path:
        runner_threads.append(threading.get_ident())
        (path / "report.html").write_text("ready", encoding="utf-8")
        await on_progress({"stage": "s01", "state": "started", "current": 1, "total": 1})
        return path / "claim_packet.json"

    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)
    caller_thread = threading.get_ident()
    await send_reply(context, AgentReply(text="Finishing now.", stop_capture=True))
    assert context.finalization_task is not None
    await context.finalization_task

    assert runner_threads and runner_threads[0] != caller_thread
    assert any(message.get("type") == "pipeline_progress" for message in socket.messages)
    assert any(
        message.get("type") == "agent_text"
        and message.get("text") == "Done. I found 12 books, 7 identified. The report is ready."
        for message in socket.messages
    )
    assert socket.messages[-1] == {
        "type": "packet_ready",
        "report_url": f"/sweeps/{sweep_id}/",
    }


def test_report_routes_and_path_safety(tmp_path: Path) -> None:
    sweep_id = "sw_20261127_120000_ab12"
    sweep_dir = tmp_path / sweep_id
    sweep_dir.mkdir()
    (sweep_dir / "sweep.json").write_text("{}", encoding="utf-8")
    (sweep_dir / "report.html").write_text("<h1>Report</h1>", encoding="utf-8")
    (sweep_dir / "frames").mkdir()
    (sweep_dir / "frames" / "f.jpg").write_bytes(b"frame")
    client = TestClient(create_app(Settings(_env_file=None, sweeps_dir=tmp_path)))

    assert client.get("/sweeps").status_code == 200
    assert client.get("/sweeps").text.find(sweep_id) >= 0
    assert client.get(f"/sweeps/{sweep_id}/").text == "<h1>Report</h1>"
    assert client.get(f"/sweeps/{sweep_id}/frames/f.jpg").content == b"frame"
    assert client.get("/viewer").status_code == 200
    assert client.get("/architecture").status_code == 200
    with pytest.raises(HTTPException):
        report_path(tmp_path, sweep_id, "../outside.txt")


class _FakeSocket:
    def __init__(self, settings: Settings) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(settings=settings))
        self.messages: list[dict[str, object]] = []

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)


async def _packet_summary(_name: str, _arguments: dict[str, object]) -> dict[str, object]:
    return {"ready": True, "book_count": 12, "books_identified": 7}
