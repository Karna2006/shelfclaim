"""Run the text-and-vision agent loop for one capture sweep.

Input: final user text, optional current JPEG, and explicit deterministic tools.
Output: assistant text plus a capture-stop signal. Implements architecture §5.
"""

from __future__ import annotations

import logging
from collections import deque

from app.live.client import LlmClient
from app.live.intents import route_intent
from app.live.models import AgentMessage, AgentReply, LlmToolCall, LlmToolResult
from app.live.numeric_grounding import find_ungrounded_claims
from app.live.resilience import generate_with_fallback
from app.live.session import LiveSessionContext
from app.live.text import (
    deterministic_locale as _deterministic_locale,
)
from app.live.text import (
    frame_marker as _frame_marker,
)
from app.live.text import (
    limit_reply as _limit_reply,
)
from app.live.text import (
    question_script as _question_script,
)
from app.live.tools import TOOL_SCHEMAS, ToolHandlers
from app.live.transcript import TranscriptLine, append_transcript
from app.pipeline.artifacts import Event
from app.prompts.loader import ScriptedLines, load_prompt, load_scripted_lines
from app.settings import Settings
from app.telemetry.events import write_event

logger = logging.getLogger(__name__)
FALLBACK_LINE = "Sorry, say that again?"
_NUMERIC_RETRY_NOTE = (
    "Your previous reply contained a number not provided by a tool; "
    "rephrase without it or call the right tool."
)


class AgentLoop:
    """Keep a bounded dialogue and execute only the documented tool schemas."""

    def __init__(self, settings: Settings, session: LiveSessionContext, client: LlmClient) -> None:
        self.settings = settings
        self.session = session
        self.client = client
        self.tools = ToolHandlers(settings, session)
        self.system_prompt = load_prompt("agent_system")
        self.scripted_lines: ScriptedLines = load_scripted_lines()
        self._history: deque[AgentMessage] = deque()
        self._recent_tool_results: deque[object] = deque(maxlen=10)
        self._turn_count = 0
        self._blocks = 0
        self.last_model_used = "scripted"

    async def greet(self) -> AgentReply:
        """Return the reviewed opening without calling the language model."""
        self._history.append(AgentMessage(role="model", text=self.scripted_lines.opening))
        self._trim_history()
        return AgentReply(text=self.scripted_lines.opening)

    async def complete_reply(self, reply: AgentReply) -> None:
        """Run scripted actions that are sequenced after a reply is sent."""
        if reply.start_sweep_after_reply:
            await self.tools.execute("start_sweep", {})

    async def handle_user_text(self, text: str, frame_jpeg: bytes | None) -> AgentReply:
        """Append one merged final transcript and produce a tool-aware reply."""
        self._turn_count += 1
        self.session.latest_user_text = text
        frame = frame_jpeg if should_attach_frame(text, self._turn_count, self.settings) else None
        marker = _frame_marker(self.session.latest_capture_seq) if frame is not None else None
        stored_text = f"{text}\n{marker}" if marker else text
        self._history.append(AgentMessage(role="user", text=stored_text, image_jpeg=frame))
        self._trim_history()
        append_transcript(
            self.session.sweep_dir,
            TranscriptLine(t_ms=self.session.latest_client_t_ms, speaker="user", text=text),
        )
        write_event(
            self.session.sweep_dir,
            Event(
                t_ms=self.session.latest_client_t_ms, type="transcript_user", payload={"text": text}
            ),
        )
        try:
            if not self.session.locale_confirmed:
                locale = _deterministic_locale(text)
                if locale is not None:
                    self.last_model_used = "intent-router"
                    country, currency = locale
                    write_event(
                        self.session.sweep_dir,
                        Event(
                            t_ms=self.session.latest_client_t_ms,
                            type="intent_routed",
                            payload={
                                "kind": "locale",
                                "route": "deterministic",
                                "country": country,
                                "currency": currency,
                            },
                        ),
                    )
                    tool_call = LlmToolCall(
                        name="set_locale",
                        arguments={"country": country, "currency": currency},
                        call_id="deterministic-locale",
                    )
                    self._history.append(AgentMessage(role="model", tool_calls=[tool_call]))
                    result = await self.tools.execute(
                        "set_locale", {"country": country, "currency": currency}
                    )
                    self._recent_tool_results.append(result)
                    self._history.append(
                        AgentMessage(
                            role="user",
                            tool_results=[
                                LlmToolResult(
                                    name="set_locale",
                                    response=result,
                                    call_id=tool_call.call_id,
                                )
                            ],
                        )
                    )
                    if result.get("supported") is True:
                        scripted_text = self.scripted_lines.after_locale
                        self._history.append(AgentMessage(role="model", text=scripted_text))
                        self._trim_history()
                        return AgentReply(text=scripted_text, start_sweep_after_reply=True)
            intent_reply = await route_intent(self, text)
            if intent_reply is not None:
                return intent_reply
            scripted_answer = _question_script(text, self.scripted_lines)
            if scripted_answer is not None:
                self.last_model_used = "scripted"
                self._history.append(AgentMessage(role="model", text=scripted_answer))
                self._trim_history()
                return AgentReply(text=scripted_answer)
            return await self._generate()
        finally:
            self._history = deque(
                message.model_copy(update={"image_jpeg": None}) for message in self._history
            )

    def record_cue(self, text: str) -> None:
        """Add an already-spoken capture cue to future model context."""
        self._history.append(
            AgentMessage(role="model", text=f"[Capture cue already spoken: {text}]")
        )
        self._trim_history()

    async def _generate(self, event_text: str | None = None) -> AgentReply:
        if event_text:
            self._history.append(AgentMessage(role="user", text=event_text))
            self._trim_history()
        stop_capture = False
        tool_rounds = 0
        numeric_retry_used = False
        max_tokens_retried = False
        max_output_tokens = 1024
        request_system_prompt = self.system_prompt
        history_before_turn = list(self._history)
        try:
            while True:
                self.last_model_used = self.settings.agent_model
                response, model = await generate_with_fallback(
                    self.client,
                    self.settings,
                    self.session.sweep_dir,
                    self.session.latest_client_t_ms,
                    system_prompt=request_system_prompt,
                    history=list(self._history),
                    tools=TOOL_SCHEMAS,
                    max_output_tokens=max_output_tokens,
                )
                self.last_model_used = model
                self._log_response_diagnostics(response.diagnostics)
                request_system_prompt = self.system_prompt
                if not response.tool_calls:
                    if not response.text:
                        if (
                            response.diagnostics.get("finish_reason") == "MAX_TOKENS"
                            and not max_tokens_retried
                        ):
                            max_tokens_retried = True
                            max_output_tokens *= 2
                            logger.info(
                                "Retrying empty MAX_TOKENS response with max_output_tokens=%d",
                                max_output_tokens,
                            )
                            continue
                        return self._fallback_reply(
                            stop_capture,
                            "EmptyModelResponse",
                            "The model returned neither reply text nor tool calls.",
                            response.diagnostics,
                        )
                    text, was_truncated = _limit_reply(response.text)
                    if was_truncated:
                        self._log_reply_truncated(response.text, text)
                        if text == FALLBACK_LINE:
                            self._log_fallback(
                                "ReplyTooLong",
                                "No complete sentence fit within the configured reply limit.",
                            )
                    offending = find_ungrounded_claims(text, tuple(self._recent_tool_results))
                    if offending:
                        attempt = 2 if numeric_retry_used else 1
                        self._log_numeric_block(attempt, [claim.token for claim in offending])
                        if numeric_retry_used:
                            text = FALLBACK_LINE
                            self._log_fallback(
                                "UngroundedNumericClaim",
                                f"Second reply contained ungrounded claims: "
                                f"{[claim.token for claim in offending]}",
                            )
                        else:
                            numeric_retry_used = True
                            request_system_prompt = (
                                f"{self.system_prompt}\n\nSystem note: {_NUMERIC_RETRY_NOTE}"
                            )
                            continue
                    self._history.append(AgentMessage(role="model", text=text))
                    self._trim_history()
                    return AgentReply(text=text, stop_capture=stop_capture)
                if tool_rounds >= self.settings.config.agent.max_tool_rounds:
                    raise RuntimeError("Agent exceeded its configured tool-call rounds")
                tool_rounds += 1
                self._history.append(
                    AgentMessage(role="model", text=response.text, tool_calls=response.tool_calls)
                )
                results: list[LlmToolResult] = []
                locale_confirmed = False
                for call in response.tool_calls:
                    result = await self.tools.execute(call.name, call.arguments)
                    self._recent_tool_results.append(result)
                    stop_capture = stop_capture or bool(result.get("stop_capture"))
                    locale_confirmed = locale_confirmed or (
                        call.name == "set_locale" and result.get("supported") is True
                    )
                    results.append(
                        LlmToolResult(name=call.name, response=result, call_id=call.call_id)
                    )
                self._history.append(AgentMessage(role="user", tool_results=results))
                self._trim_history()
                if locale_confirmed:
                    scripted_text = self.scripted_lines.after_locale
                    self._history.append(AgentMessage(role="model", text=scripted_text))
                    self._trim_history()
                    return AgentReply(
                        text=scripted_text,
                        stop_capture=stop_capture,
                        start_sweep_after_reply=True,
                    )
        except Exception as exc:
            logger.exception("Agent call failed for sweep %s", self.session.sweep_id)
            self._history = deque(history_before_turn)
            write_event(
                self.session.sweep_dir,
                Event(
                    t_ms=self.session.latest_client_t_ms,
                    type="error",
                    payload={
                        "source": "agent",
                        "model": self.settings.agent_model,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                ),
            )
            return self._fallback_reply(stop_capture, type(exc).__name__, str(exc))

    def _fallback_reply(
        self,
        stop_capture: bool,
        exception_type: str,
        message: str,
        diagnostics: dict[str, object] | None = None,
    ) -> AgentReply:
        self._log_fallback(exception_type, message, diagnostics)
        self._history.append(AgentMessage(role="model", text=FALLBACK_LINE))
        self._trim_history()
        return AgentReply(text=FALLBACK_LINE, stop_capture=stop_capture)

    def _log_fallback(
        self,
        exception_type: str,
        message: str,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        write_event(
            self.session.sweep_dir,
            Event(
                t_ms=self.session.latest_client_t_ms,
                type="agent_fallback",
                payload={
                    "exception_type": exception_type,
                    "message": message,
                    "diagnostics": diagnostics or {},
                },
            ),
        )

    def _log_response_diagnostics(self, diagnostics: dict[str, object]) -> None:
        write_event(
            self.session.sweep_dir,
            Event(
                t_ms=self.session.latest_client_t_ms,
                type="agent_response_diagnostics",
                payload=diagnostics,
            ),
        )

    def _log_reply_truncated(self, original: str, final: str) -> None:
        write_event(
            self.session.sweep_dir,
            Event(
                t_ms=self.session.latest_client_t_ms,
                type="reply_truncated",
                payload={
                    "original_word_count": len(original.split()),
                    "final_word_count": len(final.split()),
                },
            ),
        )

    def _log_numeric_block(self, attempt: int, offending_tokens: list[str]) -> None:
        logger.warning(
            "Blocked ungrounded numeric reply for sweep %s attempt=%d tokens=%s",
            self.session.sweep_id,
            attempt,
            offending_tokens,
        )
        write_event(
            self.session.sweep_dir,
            Event(
                t_ms=self.session.latest_client_t_ms,
                type="numeric_claim_blocked",
                payload={"attempt": attempt, "offending_tokens": offending_tokens},
            ),
        )

    def _trim_history(self) -> None:
        messages = list(self._history)
        user_turns = [
            index
            for index, message in enumerate(messages)
            if message.role == "user" and not message.tool_results
        ]
        keep_turns = self.settings.config.agent.history_turns
        if len(user_turns) > keep_turns:
            start = user_turns[-keep_turns]
            if messages[start].tool_results and start > 0 and messages[start - 1].tool_calls:
                start -= 1
            messages = messages[start:]
        max_messages = keep_turns * 4 + 4
        while len(messages) > max_messages:
            turns = [
                index
                for index, message in enumerate(messages)
                if message.role == "user" and not message.tool_results
            ]
            if len(turns) > 1:
                messages = messages[turns[1] :]
            elif turns:
                break
            else:
                messages.pop(0)
        self._history = deque(messages)


def should_attach_frame(text: str, turn_number: int, settings: Settings) -> bool:
    """Attach a JPEG for visible-reference questions or every configured N turns."""
    keywords = settings.config.agent.frame_attachment_keywords
    normalized = text.casefold()
    referenced = any(keyword.casefold() in normalized for keyword in keywords)
    every_n = settings.config.agent.frame_attachment_every_n_turns
    return referenced or turn_number % every_n == 0
