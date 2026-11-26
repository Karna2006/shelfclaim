"""Serve the text-only live-agent WebSocket for a capture sweep.

Input: final transcripts, low-resolution JPEGs, and stop controls. Output:
agent replies and priority cues; raw microphone audio is never accepted.
"""

from __future__ import annotations

import asyncio
import logging
import re

from app.live.agent import AgentLoop
from app.live.models import (
    AgentReply,
    ControlMessage,
    LiveFrameMessage,
    LlmResponse,
    UserTextMessage,
    parse_live_message,
)
from app.live.session import LiveSessionContext
from app.live.transcript import TranscriptLine, append_transcript
from app.pipeline.artifacts import Event
from app.settings import Settings
from app.telemetry.events import write_event
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
_SWEEP_ID = re.compile(r"sw_\d{8}_\d{6}_[0-9a-f]{4}")


async def live_socket(websocket: WebSocket, sweep_id: str) -> None:
    """Receive final speech text, merge burst finals, and maintain agent turns."""
    settings: Settings = websocket.app.state.settings
    sweep_dir = settings.sweeps_dir / sweep_id
    sessions = websocket.app.state.live_sessions
    context = sessions.get(sweep_id)
    if (
        not _SWEEP_ID.fullmatch(sweep_id)
        or context is None
        or not (sweep_dir / "sweep.json").is_file()
    ):
        await websocket.close(code=1008, reason="Unknown sweep")
        return

    await websocket.accept()
    context.websocket = websocket
    try:
        client = websocket.app.state.llm_client_factory(settings, websocket.app.state.model_limiter)
        context.agent = AgentLoop(settings, context, client)
    except Exception:
        logger.exception("Could not initialize agent client")
        context.agent = AgentLoop(settings, context, _UnavailableLlmClient())
    await websocket.send_json({"type": "state", "state": "listening"})
    async with context.turn_lock:
        await _send_reply(context, await context.agent.greet())

    pending: list[str] = []
    pending_since: float | None = None
    debounce_s = settings.config.agent.debounce_ms / 1000
    try:
        while True:
            timeout = None
            if pending_since is not None:
                timeout = max(0.0, pending_since + debounce_s - asyncio.get_running_loop().time())
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
            except TimeoutError:
                if pending:
                    text = " ".join(pending).strip()
                    pending.clear()
                    pending_since = None
                    async with context.turn_lock:
                        await _send_reply(
                            context,
                            await context.agent.handle_user_text(text, context.latest_frame_jpeg),
                        )
                continue
            try:
                message = parse_live_message(raw)
            except ValueError:
                await websocket.send_json({"type": "error", "message": "Unsupported live message"})
                continue
            if isinstance(message, ControlMessage):
                break
            if isinstance(message, LiveFrameMessage):
                context.latest_frame_jpeg = message.jpeg_bytes()
                context.latest_client_t_ms = message.t_ms
                continue
            _queue_final_text(context, message, pending)
            if pending:
                pending_since = asyncio.get_running_loop().time()
    except WebSocketDisconnect:
        pass
    finally:
        context.websocket = None
        close = getattr(client if "client" in locals() else None, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                logger.exception("Could not close agent model client")


def _queue_final_text(
    context: LiveSessionContext, message: UserTextMessage, pending: list[str]
) -> None:
    """Discard recent agent echo, otherwise queue a final transcript for debounce."""
    match = context.echo_guard.match(message.text)
    if match is not None:
        write_event(
            context.sweep_dir,
            Event(
                t_ms=message.t_ms,
                type="echo_dropped",
                payload={
                    "text": message.text,
                    "matched_line": match.text,
                    "similarity": match.similarity,
                },
            ),
        )
        return
    context.latest_client_t_ms = message.t_ms
    pending.append(message.text.strip())


async def _send_reply(context: LiveSessionContext, reply: AgentReply) -> None:
    text = reply.text
    append_transcript(
        context.sweep_dir,
        TranscriptLine(t_ms=context.latest_client_t_ms, speaker="agent", text=text),
    )
    write_event(
        context.sweep_dir,
        Event(t_ms=context.latest_client_t_ms, type="transcript_agent", payload={"text": text}),
    )
    context.echo_guard.add_spoken_line(text)
    if context.websocket is not None:
        await context.websocket.send_json(
            {"type": "agent_text", "text": text, "t_ms": context.latest_client_t_ms}
        )
        if reply.start_sweep_after_reply and context.agent is not None:
            await context.agent.complete_reply(reply)
        if reply.stop_capture:
            await context.websocket.send_json({"type": "control", "action": "stop_capture"})


async def send_cue(context: LiveSessionContext, text: str, priority: int = 10) -> None:
    """Send a non-LLM cue that is logged, remembered, and spoken urgently."""
    if not text.strip():
        return
    cue = text.strip()
    append_transcript(
        context.sweep_dir,
        TranscriptLine(t_ms=context.latest_client_t_ms, speaker="cue", text=cue),
    )
    write_event(
        context.sweep_dir,
        Event(
            t_ms=context.latest_client_t_ms,
            type="cue_sent",
            payload={"text": cue, "priority": priority},
        ),
    )
    context.echo_guard.add_spoken_line(cue)
    if context.agent is not None:
        context.agent.record_cue(cue)
    if context.websocket is not None:
        await context.websocket.send_json({"type": "cue", "text": cue, "priority": priority})


class _UnavailableLlmClient:
    async def generate(self, **_: object) -> LlmResponse:
        raise RuntimeError("Agent model client is unavailable")
