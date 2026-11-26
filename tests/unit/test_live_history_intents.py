from __future__ import annotations

from collections import deque
from pathlib import Path

from app.live.agent import AgentLoop
from app.live.intents import classify_intent
from app.live.models import AgentMessage, LlmResponse, LlmToolCall, LlmToolResult
from app.live.session import LiveSessionContext
from app.packet.models import Sweep
from app.settings import Settings, YamlSettings


class EmptyClient:
    async def generate(self, **_: object) -> LlmResponse:
        raise AssertionError("a deterministic intent must not call the model")


def _make_agent(tmp_path: Path) -> AgentLoop:
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
    return AgentLoop(
        Settings(config=YamlSettings(), _env_file=None),
        LiveSessionContext(sweep_id, tmp_path),
        EmptyClient(),
    )


def test_configured_intents_extract_statement_kind_and_target() -> None:
    excluded = classify_intent("Skip the bottom shelf on the right, it's not mine")
    print_copy = classify_intent("This is a print")
    title = classify_intent("Which book is this?")
    price = classify_intent("What's it worth?")

    assert excluded is not None
    assert excluded["kind"] == "not_mine"
    assert excluded["target_hint"] == "the bottom shelf"
    assert print_copy is not None and print_copy["kind"] == "print"
    assert title is not None and title["kind"] == "title"
    assert price is not None and price["kind"] == "price"


def test_history_keeps_last_eight_turns_and_function_pairs_together(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    history = []
    for index in range(10):
        history.append(AgentMessage(role="user", text=f"turn {index}"))
        if index in {0, 8}:
            call_id = f"call-{index}"
            history.append(
                AgentMessage(
                    role="model",
                    tool_calls=[
                        LlmToolCall(
                            name="get_sweep_status",
                            call_id=call_id,
                            thought_signature=b"thought-signature",
                        )
                    ],
                )
            )
            history.append(
                AgentMessage(
                    role="user",
                    tool_results=[
                        LlmToolResult(
                            name="get_sweep_status",
                            call_id=call_id,
                            response={"frames_seen": 2},
                        )
                    ],
                )
            )
        history.append(AgentMessage(role="model", text=f"reply {index}"))
    agent._history = deque(history)

    agent._trim_history()

    retained = list(agent._history)
    turns = [m.text for m in retained if m.role == "user" and not m.tool_results]
    call_ids = {call.call_id for message in retained for call in message.tool_calls}
    result_ids = {result.call_id for message in retained for result in message.tool_results}
    assert turns == [f"turn {index}" for index in range(2, 10)]
    assert call_ids == result_ids == {"call-8"}
    assert next(call for message in retained for call in message.tool_calls).thought_signature == (
        b"thought-signature"
    )
