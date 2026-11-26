"""Send agent replies and capture cues to the active browser session.

Input: per-sweep session state and normalized agent or monitor output. Output:
WebSocket messages, transcript lines, and delivery telemetry for docs/04 §4.3, §5.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.live.agent import FALLBACK_LINE
from app.live.models import AgentReply
from app.live.session import LiveSessionContext
from app.live.transcript import TranscriptLine, append_transcript
from app.pipeline.artifacts import Event
from app.telemetry.events import write_event

logger = logging.getLogger(__name__)


async def send_reply(context: LiveSessionContext, reply: AgentReply) -> None:
    """Persist and send one agent reply, then run any post-speech action."""
    context.agent_reply_active = True
    append_transcript(
        context.sweep_dir,
        TranscriptLine(t_ms=context.latest_client_t_ms, speaker="agent", text=reply.text),
    )
    write_event(
        context.sweep_dir,
        Event(
            t_ms=context.latest_client_t_ms,
            type="transcript_agent",
            payload={"text": reply.text},
        ),
    )
    context.echo_guard.add_spoken_line(reply.text)
    if context.websocket is None:
        return
    await context.websocket.send_json(
        {"type": "agent_text", "text": reply.text, "t_ms": context.latest_client_t_ms}
    )
    if reply.start_sweep_after_reply and context.agent is not None:
        await context.agent.complete_reply(reply)
    if reply.stop_capture:
        await context.websocket.send_json({"type": "control", "action": "stop_capture"})
    report_path = context.sweep_dir / "report.html"
    if report_path.is_file() and not context.packet_ready_sent:
        context.packet_ready_sent = True
        await context.websocket.send_json(
            {"type": "packet_ready", "report_url": f"/api/sweeps/{context.sweep_id}/report"}
        )


async def handle_user_turn(context: LiveSessionContext, text: str) -> None:
    """Run one agent turn, speak one optional filler, and log final reply latency."""
    if context.agent is None:
        return
    started = time.monotonic()
    context.agent_turn_pending = True
    task = asyncio.create_task(context.agent.handle_user_text(text, context.latest_frame_jpeg))
    try:
        reply = await asyncio.wait_for(
            asyncio.shield(task), timeout=context.agent.settings.config.agent.filler_after_s
        )
    except TimeoutError:
        await _send_filler(context)
        try:
            reply = await task
        except Exception as exc:
            _log_turn_failure(context, exc)
            reply = AgentReply(text=FALLBACK_LINE)
    except Exception as exc:
        _log_turn_failure(context, exc)
        reply = AgentReply(text=FALLBACK_LINE)
    latency_ms = round((time.monotonic() - started) * 1000)
    context.agent_turn_pending = False
    write_event(
        context.sweep_dir,
        Event(
            t_ms=context.latest_client_t_ms,
            type="agent_reply",
            payload={
                "latency_ms": latency_ms,
                "model": context.agent.last_model_used,
                "text": reply.text,
            },
        ),
    )
    await send_reply(context, reply)


async def run_turn_queue(context: LiveSessionContext, queue: asyncio.Queue[str]) -> None:
    """Process accepted user turns in order while the WebSocket keeps receiving input."""
    while True:
        text = await queue.get()
        try:
            context.agent_turn_pending = True
            if context.websocket is not None:
                await context.websocket.send_json({"type": "state", "state": "thinking"})
            await handle_user_turn(context, text)
        finally:
            queue.task_done()


async def send_cue(
    context: LiveSessionContext,
    text: str,
    priority: int = 10,
    *,
    kind: str = "capture",
    metrics: dict[str, object] | None = None,
) -> bool:
    """Send a logged, non-LLM cue unless user or agent speech has priority."""
    if not text.strip():
        return False
    reason = cue_suppression_reason(context)
    if reason:
        write_event(
            context.sweep_dir,
            Event(
                t_ms=context.latest_client_t_ms,
                type="cue_suppressed",
                payload={"text": text.strip(), "kind": kind, "reason": reason},
            ),
        )
        return False
    cue = text.strip()
    if not context.earphones_mode:
        cue = " ".join(cue.split()[: context.cue_max_words])
    append_transcript(
        context.sweep_dir,
        TranscriptLine(t_ms=context.latest_client_t_ms, speaker="cue", text=cue),
    )
    write_event(
        context.sweep_dir,
        Event(
            t_ms=context.latest_client_t_ms,
            type="cue_sent",
            payload={"text": cue, "priority": priority, "kind": kind, "metrics": metrics or {}},
        ),
    )
    context.echo_guard.add_spoken_line(cue)
    if context.agent is not None:
        context.agent.record_cue(cue)
    if context.websocket is not None:
        await context.websocket.send_json(
            {"type": "cue", "text": cue, "priority": priority, "kind": kind}
        )
    return True


def cue_suppression_reason(context: LiveSessionContext) -> str | None:
    """Return why capture guidance must wait for the current conversation."""
    if context.user_speaking:
        return "user_speaking"
    if (
        context.last_user_speech_at is not None
        and time.monotonic() - context.last_user_speech_at < context.cue_suppress_after_user_s
    ):
        return "user_speech_cooldown"
    if context.agent_turn_pending:
        return "agent_turn_pending"
    return None


async def _send_filler(context: LiveSessionContext) -> None:
    """Log and speak a single latency filler without adding an LLM turn."""
    text = "One moment."
    append_transcript(
        context.sweep_dir,
        TranscriptLine(t_ms=context.latest_client_t_ms, speaker="agent", text=text),
    )
    write_event(
        context.sweep_dir,
        Event(
            t_ms=context.latest_client_t_ms,
            type="transcript_agent",
            payload={"text": text, "kind": "filler"},
        ),
    )
    context.echo_guard.add_spoken_line(text)
    if context.agent is not None:
        context.agent.record_cue(text)
    if context.websocket is not None:
        await context.websocket.send_json(
            {"type": "agent_text", "text": text, "t_ms": context.latest_client_t_ms}
        )


def _log_turn_failure(context: LiveSessionContext, exc: Exception) -> None:
    write_event(
        context.sweep_dir,
        Event(
            t_ms=context.latest_client_t_ms,
            type="agent_fallback",
            payload={"exception_type": type(exc).__name__, "message": str(exc)},
        ),
    )
    logger.error("Unhandled live-agent turn failure: %s: %s", type(exc).__name__, exc)
