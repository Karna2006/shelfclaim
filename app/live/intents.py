"""Load reviewed deterministic voice intents and extract statement targets.

Input: a final transcript. Output: a compact intent with safe tool arguments;
wording and matching phrases live in `app/prompts/agent_intents.yaml`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from app.live.models import AgentMessage, AgentReply, LlmToolCall, LlmToolResult

_INTENT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "agent_intents.yaml"

if TYPE_CHECKING:
    from app.live.agent import AgentLoop


def classify_intent(text: str) -> dict[str, str] | None:
    """Return the first configured statement or question intent for this text."""
    config = yaml.safe_load(_INTENT_PATH.read_text(encoding="utf-8"))
    normalized = _normalize(text)
    for kind, spec in config["statements"].items():
        if any(_contains_phrase(normalized, phrase) for phrase in spec["phrases"]):
            return {
                "kind": kind,
                "target_hint": _target_hint(text, kind),
                "confirmation": str(spec["confirmation"]),
            }
    for intent, key in (
        ("done", "done_phrases"),
        ("count", "count_phrases"),
        ("missed", "missed_phrases"),
        ("title", "title_phrases"),
        ("price", "price_phrases"),
    ):
        if any(_contains_phrase(normalized, phrase) for phrase in config["other"][key]):
            return {"kind": intent, **_scripted_values(config["other"], intent)}
    return None


async def route_intent(agent: AgentLoop, text: str) -> AgentReply | None:
    """Execute a classified common intent using the real deterministic tools."""
    intent = classify_intent(text)
    if intent is None:
        return None
    kind = intent["kind"]
    agent.last_model_used = "intent-router"
    if kind in {
        "print",
        "original",
        "first_edition",
        "signed",
        "rare",
        "not_mine",
        "exclude_region",
    }:
        await _record_tool(
            "record_user_statement",
            {"kind": kind, "target_hint": intent["target_hint"], "text": text},
            agent,
        )
        return _remember(agent, intent["confirmation"])
    if kind in {"done", "count", "missed"}:
        status = await _record_tool("get_sweep_status", {}, agent)
        coverage = status.get("coverage", {})
        gaps = coverage.get("rows_needing_review", []) if isinstance(coverage, dict) else []
        if kind == "done" and (
            not isinstance(coverage, dict) or not coverage.get("available", False)
        ):
            config = yaml.safe_load(_INTENT_PATH.read_text(encoding="utf-8"))
            return _remember(agent, config["other"]["coverage_unavailable"])
        if kind == "count":
            count = status.get("provisional_book_count")
            line = (
                f"I count {count} books so far."
                if count is not None
                else "I don't have a confirmed book count yet."
            )
            return _remember(agent, line)
        if kind == "missed":
            if gaps:
                return _remember(
                    agent,
                    f"Please capture these rows before we finish: {', '.join(map(str, gaps))}.",
                )
            return _remember(agent, "I don't see any rows marked for review.")
        if gaps:
            return _remember(
                agent, f"Please capture these rows before we finish: {', '.join(map(str, gaps))}."
            )
        stopped = await _record_tool("end_sweep", {}, agent)
        if stopped.get("stopped") is True:
            reply = _remember(agent, intent["confirmation"])
            return reply.model_copy(update={"stop_capture": True})
        return _remember(
            agent, str(stopped.get("ask_user") or "Are all shelves and rows captured?")
        )
    if kind in {"title", "price"}:
        return _remember(agent, intent["confirmation"])
    return None


async def _record_tool(
    name: str, arguments: dict[str, object], agent: AgentLoop
) -> dict[str, object]:
    call_id = f"intent-{agent._turn_count}-{name}"
    agent._history.append(
        AgentMessage(
            role="model",
            tool_calls=[LlmToolCall(name=name, arguments=arguments, call_id=call_id)],
        )
    )
    result = await agent.tools.execute(name, arguments)
    agent._recent_tool_results.append(result)
    agent._history.append(
        AgentMessage(
            role="user",
            tool_results=[LlmToolResult(name=name, response=result, call_id=call_id)],
        )
    )
    agent._trim_history()
    return result


def _remember(agent: AgentLoop, text: str) -> AgentReply:
    agent._history.append(AgentMessage(role="model", text=text))
    agent._trim_history()
    return AgentReply(text=text)


def _scripted_values(other: dict[str, Any], intent: str) -> dict[str, str]:
    keys = {"title": "title", "price": "price", "done": "done"}
    return {"confirmation": str(other[keys[intent]])} if intent in keys else {}


def _target_hint(text: str, kind: str) -> str:
    normalized = text.strip(" .,!?")
    match = re.search(
        r"(?:this|that|the)\s+(?:bottom|top|left|right)?\s*(?:shelf|book|painting|portrait|item|area)",
        normalized,
        re.I,
    )
    if match:
        return match.group(0).casefold()
    if kind == "exclude_region":
        return "shelf or area described by the user"
    if kind == "not_mine":
        return "area described by the user"
    return "current item"


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.casefold()))


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize(phrase)
    return f" {normalized_phrase} " in f" {text} "
