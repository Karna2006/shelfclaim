from __future__ import annotations

import json
from pathlib import Path

from app.live.agent import AgentLoop
from app.live.models import LlmResponse
from app.live.session import LiveSessionContext
from app.packet.models import Sweep
from app.settings import Settings, YamlSettings


def _setup(tmp_path: Path, *, models: list[str], backoffs: list[float]):
    settings = Settings(config=YamlSettings(), _env_file=None)
    agent_config = settings.config.agent.model_copy(
        update={"model_chain": models, "retry_backoff_s": backoffs}
    )
    config = settings.config.model_copy(update={"agent": agent_config})
    settings = settings.model_copy(update={"config": config})
    sweep_id = "sw_20261126_030042_1552"
    sweep = Sweep(
        id=sweep_id,
        captured_at="2026-11-26T03:00:42+05:30",
        device="test",
        duration_s=0,
        country="IN",
        currency="INR",
        locale_config="config/locales/IN.yaml",
    )
    (tmp_path / "sweep.json").write_text(sweep.model_dump_json(), encoding="utf-8")
    return settings, LiveSessionContext(sweep_id, tmp_path)


async def test_server_error_retries_then_replies_and_logs_attempt_shape(tmp_path: Path) -> None:
    class ServerError(Exception):
        status_code = 500

    class RetryClient:
        def __init__(self) -> None:
            self.models: list[str] = []

        async def generate(self, **kwargs: object) -> LlmResponse:
            self.models.append(str(kwargs["model"]))
            if len(self.models) == 1:
                raise ServerError("500 INTERNAL")
            return LlmResponse(
                text="I can help with that.",
                diagnostics={"usage_metadata": {"prompt_token_count": 123}},
            )

    client = RetryClient()
    settings, session = _setup(tmp_path, models=["gemini-3.1-flash-lite"], backoffs=[0.0, 0.0])
    agent = AgentLoop(settings, session, client)

    reply = await agent.handle_user_text("Tell me about the shelf", b"small jpeg")

    assert reply.text == "I can help with that."
    assert client.models == ["gemini-3.1-flash-lite"] * 2
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    request = next(event for event in events if event["type"] == "agent_request")
    failure = next(
        event
        for event in events
        if event["type"] == "agent_attempt" and event["payload"].get("success") is False
    )
    success = next(
        event
        for event in events
        if event["type"] == "agent_attempt" and event["payload"].get("success") is True
    )
    assert request["payload"]["image_parts"] == 1
    assert request["payload"]["image_bytes"] == len(b"small jpeg")
    assert failure["payload"]["error_type"] == "ServerError"
    assert success["payload"]["total_prompt_tokens"] == 123
    assert all(message.image_jpeg is None for message in agent._history)


async def test_model_chain_falls_back_after_primary_retries(tmp_path: Path) -> None:
    class ServerError(Exception):
        status_code = 500

    class ChainClient:
        def __init__(self) -> None:
            self.models: list[str] = []

        async def generate(self, **kwargs: object) -> LlmResponse:
            model = str(kwargs["model"])
            self.models.append(model)
            if model == "gemini-3.1-flash-lite":
                raise ServerError("500 INTERNAL")
            return LlmResponse(text="The sweep is continuing.")

    client = ChainClient()
    settings, session = _setup(
        tmp_path,
        models=["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
        backoffs=[0.0, 0.0],
    )
    agent = AgentLoop(settings, session, client)

    reply = await agent.handle_user_text("Keep going", None)

    assert reply.text == "The sweep is continuing."
    assert client.models == [
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
    ]
    assert agent.last_model_used == "gemini-3.5-flash-lite"


async def test_all_models_retry_once_without_current_image(tmp_path: Path) -> None:
    class ServerError(Exception):
        status_code = 500

    class ImageSensitiveClient:
        def __init__(self) -> None:
            self.image_counts: list[int] = []

        async def generate(self, **kwargs: object) -> LlmResponse:
            history = kwargs["history"]
            count = sum(message.image_jpeg is not None for message in history)
            self.image_counts.append(count)
            if count:
                raise ServerError("500 INTERNAL with image")
            return LlmResponse(text="I can see the shelf.")

    client = ImageSensitiveClient()
    settings, session = _setup(tmp_path, models=["gemini-3.1-flash-lite"], backoffs=[])
    agent = AgentLoop(settings, session, client)

    reply = await agent.handle_user_text("What is this?", b"frame bytes")

    assert reply.text == "I can see the shelf."
    assert client.image_counts == [1, 0]
    assert all(message.image_jpeg is None for message in agent._history)
