from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.live.agent import FALLBACK_LINE, AgentLoop, _question_script, should_attach_frame
from app.live.models import LlmResponse, LlmToolCall
from app.live.session import LiveSessionContext
from app.packet.models import Sweep
from app.prompts.loader import load_scripted_lines
from app.settings import Settings, YamlSettings


class FakeLlmClient:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def generate(self, **kwargs: object) -> LlmResponse:
        self.calls.append(kwargs)
        result = self.responses.pop(0)
        return result


def make_session(tmp_path: Path) -> LiveSessionContext:
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
    return LiveSessionContext("sw_20261126_030042_1552", tmp_path)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(config=YamlSettings(), sweeps_dir=tmp_path, _env_file=None)


def test_title_and_price_questions_use_reviewed_lines() -> None:
    lines = load_scripted_lines()
    assert _question_script("Which book is this?", lines) == (
        "I'll identify each book from its spine when we finish."
    )
    assert _question_script("How much is it worth?", lines) == (
        "I'll price everything from real sources when we finish."
    )


async def test_print_statement_routes_to_tool_and_saves_current_frame_seq(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    session.latest_capture_seq = 7
    fake = FakeLlmClient([])
    agent = AgentLoop(make_settings(tmp_path), session, fake)

    reply = await agent.handle_user_text("It's a print", None)

    assert reply.text == "Okay, I recorded that as a print."
    assert fake.calls == []
    saved = json.loads((tmp_path / "user_statements.jsonl").read_text(encoding="utf-8"))
    assert saved["frame_seq"] == 7
    assert saved["text"] == "It's a print"
    assert saved["value"] is None


async def test_visible_frame_is_used_for_turn_then_removed_from_rolling_history(
    tmp_path: Path,
) -> None:
    fake = FakeLlmClient([LlmResponse(text="I can see the shelf.")])
    session = make_session(tmp_path)
    agent = AgentLoop(make_settings(tmp_path), session, fake)
    await agent.handle_user_text("What is this book?", b"jpeg")

    request_history = fake.calls[0]["history"]
    assert isinstance(request_history, list)
    assert request_history[-1].image_jpeg == b"jpeg"
    assert "[frame f_latest]" in request_history[-1].text
    assert all(message.image_jpeg is None for message in agent._history)


async def test_agent_failure_returns_short_fallback_and_logs(tmp_path: Path) -> None:
    class FailingClient:
        async def generate(self, **_: object) -> LlmResponse:
            raise TimeoutError("deadline")

    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), FailingClient())
    reply = await agent.handle_user_text("Hello", None)
    assert reply.text == FALLBACK_LINE
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    fallback = [event for event in events if event["type"] == "agent_fallback"][-1]
    assert fallback["payload"]["exception_type"] == "TimeoutError"
    assert fallback["payload"]["message"] == "deadline"


async def test_failed_tool_turn_is_rolled_back_before_the_next_user_turn(tmp_path: Path) -> None:
    class FailAfterToolClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def generate(self, **kwargs: object) -> LlmResponse:
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return LlmResponse(tool_calls=[LlmToolCall(name="get_sweep_status")])
            if len(self.calls) == 2:
                raise RuntimeError("failure after tool result")
            return LlmResponse(text="I can help with that.")

    client = FailAfterToolClient()
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), client)

    failed_reply = await agent.handle_user_text("How is the sweep?", None)
    next_reply = await agent.handle_user_text("Please continue.", None)

    assert failed_reply.text == FALLBACK_LINE
    assert next_reply.text == "I can help with that."
    next_history = client.calls[2]["history"]
    assert isinstance(next_history, list)
    assert all(not message.tool_calls and not message.tool_results for message in next_history)
    assert [message.text for message in next_history if message.role == "model"] == [FALLBACK_LINE]


async def test_scripted_opening_and_locale_instruction_skip_extra_model_turn(
    tmp_path: Path,
) -> None:
    opening = (
        "Hi, I'm your claim assistant. I'll guide you through one slow walk past your shelves. "
        "Are you in India, with values in rupees?"
    )
    after_locale = "Great. Start with the shelf on your left, top row, and move slowly."
    fake = FakeLlmClient([])
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    opening_reply = await agent.greet()
    locale_reply = await agent.handle_user_text("Yes, India and rupees", None)

    assert opening_reply.text == opening
    assert len(fake.calls) == 0
    assert locale_reply.text == after_locale
    assert locale_reply.start_sweep_after_reply is True
    await agent.complete_reply(locale_reply)
    event_types = [
        json.loads(line)["type"]
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert event_types.count("tool_call") == 2


@pytest.mark.parametrize("answer", ["yes", "yeah", "yep", "correct", "haan", "ha", "right", "sure"])
async def test_affirmative_locale_answers_skip_the_llm(answer: str, tmp_path: Path) -> None:
    fake = FakeLlmClient([])
    session = make_session(tmp_path)
    agent = AgentLoop(make_settings(tmp_path), session, fake)

    reply = await agent.handle_user_text(answer, None)
    await agent.complete_reply(reply)
    sweep = Sweep.model_validate_json((tmp_path / "sweep.json").read_text(encoding="utf-8"))

    assert reply.text == agent.scripted_lines.after_locale
    assert fake.calls == []
    assert session.locale_confirmed is True
    assert (sweep.country, sweep.currency) == ("IN", "INR")


@pytest.mark.parametrize("answer", ["UK", "pounds", "GBP"])
async def test_uk_locale_answers_select_gb_without_the_llm(answer: str, tmp_path: Path) -> None:
    fake = FakeLlmClient([])
    session = make_session(tmp_path)
    agent = AgentLoop(make_settings(tmp_path), session, fake)

    reply = await agent.handle_user_text(answer, None)
    sweep = Sweep.model_validate_json((tmp_path / "sweep.json").read_text(encoding="utf-8"))

    assert reply.start_sweep_after_reply is True
    assert fake.calls == []
    assert (sweep.country, sweep.currency) == ("GB", "GBP")


async def test_empty_max_tokens_response_retries_once_with_double_limit(tmp_path: Path) -> None:
    fake = FakeLlmClient(
        [
            LlmResponse(
                diagnostics={
                    "finish_reason": "MAX_TOKENS",
                    "usage_metadata": {"thoughts_token_count": 77, "candidates_token_count": None},
                    "prompt_feedback": None,
                    "has_text_part": False,
                    "has_function_call_part": False,
                }
            ),
            LlmResponse(text="I can help with that."),
        ]
    )
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    reply = await agent.handle_user_text("Can you help?", None)

    assert reply.text == "I can help with that."
    assert [call["max_output_tokens"] for call in fake.calls] == [1024, 2048]
    assert [call["thinking_level"] for call in fake.calls] == ["minimal", "minimal"]
    assert (
        len(
            [
                line
                for line in (tmp_path / "events.jsonl").read_text().splitlines()
                if "agent_fallback" in line
            ]
        )
        == 0
    )


async def test_empty_response_fallback_contains_response_diagnostics(tmp_path: Path) -> None:
    diagnostics = {
        "finish_reason": "SAFETY",
        "usage_metadata": {"thoughts_token_count": 0, "candidates_token_count": None},
        "prompt_feedback": {"block_reason": "OTHER"},
        "block_reason": "OTHER",
        "has_text_part": False,
        "has_function_call_part": False,
    }
    fake = FakeLlmClient([LlmResponse(diagnostics=diagnostics)])
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    reply = await agent.handle_user_text("Say hello", None)

    assert reply.text == FALLBACK_LINE
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    fallback = next(event for event in events if event["type"] == "agent_fallback")
    response_log = next(event for event in events if event["type"] == "agent_response_diagnostics")
    assert fallback["payload"]["diagnostics"] == diagnostics
    assert response_log["payload"] == diagnostics


async def test_long_reply_is_truncated_and_logged(tmp_path: Path) -> None:
    fake = FakeLlmClient(
        [
            LlmResponse(
                text=(
                    "First sentence is short. Second sentence ends here. Third sentence is removed."
                )
            )
        ]
    )
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    reply = await agent.handle_user_text("Tell me something", None)

    assert reply.text == "First sentence is short. Second sentence ends here."
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["type"] == "reply_truncated" for event in events)


async def test_second_shelf_positional_reply_passes_without_tool_numbers(tmp_path: Path) -> None:
    fake = FakeLlmClient([LlmResponse(text="Go to the second shelf.")])
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    reply = await agent.handle_user_text("Where should I go?", None)

    assert reply.text == "Go to the second shelf."
    assert len(fake.calls) == 1


async def test_unsupported_number_is_blocked_after_one_failed_regeneration(
    tmp_path: Path,
) -> None:
    fake = FakeLlmClient(
        [
            LlmResponse(text="You have 80 books."),
            LlmResponse(text="You have eighty books."),
        ]
    )
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    reply = await agent.handle_user_text("Tell me a number about the books.", None)

    assert reply.text == FALLBACK_LINE
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    blocked = [event for event in events if event["type"] == "numeric_claim_blocked"]
    assert [event["payload"]["offending_tokens"] for event in blocked] == [["80"], ["eighty"]]
    fallback = [event for event in events if event["type"] == "agent_fallback"][-1]
    assert fallback["payload"]["exception_type"] == "UngroundedNumericClaim"


async def test_how_many_books_answers_from_status_tool_without_llm(tmp_path: Path) -> None:
    fake = FakeLlmClient([])
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    async def status_with_count(_: str, __: dict[str, object]) -> dict[str, object]:
        return {
            "provisional_book_count": 12,
            "coverage": {"available": True, "rows_needing_review": []},
        }

    agent.tools.execute = status_with_count
    reply = await agent.handle_user_text("How many books?", None)

    assert reply.text == "I count 12 books so far."
    assert fake.calls == []


async def test_approximate_rounded_currency_matches_tool_summary(tmp_path: Path) -> None:
    fake = FakeLlmClient(
        [
            LlmResponse(tool_calls=[LlmToolCall(name="get_packet_summary")]),
            LlmResponse(text="The total is about 21,000 rupees."),
        ]
    )
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    async def summary_with_total(_: str, __: dict[str, object]) -> dict[str, object]:
        return {"replacement_total": 21450.0}

    agent.tools.execute = summary_with_total
    reply = await agent.handle_user_text("What is the total?", None)

    assert reply.text == "The total is about 21,000 rupees."


async def test_numeric_retry_uses_system_note_and_accepts_clean_rephrase(tmp_path: Path) -> None:
    fake = FakeLlmClient(
        [
            LlmResponse(text="There are 80 books."),
            LlmResponse(text="I can't confirm that yet."),
        ]
    )
    agent = AgentLoop(make_settings(tmp_path), make_session(tmp_path), fake)

    reply = await agent.handle_user_text("Tell me a number about the books.", None)

    assert reply.text == "I can't confirm that yet."
    assert len(fake.calls) == 2
    assert (
        "Your previous reply contained a number not provided by a tool; "
        "rephrase without it or call the right tool." in fake.calls[1]["system_prompt"]
    )


async def test_end_sweep_waits_for_coverage_confirmation(tmp_path: Path) -> None:
    fake = FakeLlmClient([])
    session = make_session(tmp_path)
    agent = AgentLoop(make_settings(tmp_path), session, fake)

    reply = await agent.handle_user_text("I'm done", None)

    assert reply.stop_capture is False
    assert "captured all shelves and rows" in reply.text
    assert fake.calls == []


def test_frame_attachment_uses_configured_reference_terms_and_interval(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert should_attach_frame("What is this?", 1, settings)
    assert not should_attach_frame("Please keep going", 1, settings)
    assert should_attach_frame("Please keep going", 3, settings)
