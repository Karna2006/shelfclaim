"""Serve the text-only live-agent WebSocket for a capture sweep.

Input: final transcripts, low-resolution JPEGs, and stop controls. Output:
agent replies and priority cues; raw microphone audio is never accepted.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from app.live.agent import AgentLoop
from app.live.models import (
    ControlMessage,
    LiveFrameMessage,
    LlmResponse,
    SpeechActivityMessage,
    SpeechEventMessage,
    UserTextMessage,
    parse_live_message,
)
from app.live.session import LiveSessionContext
from app.pipeline.artifacts import Event
from app.server.live_output import (
    run_turn_queue as _run_turn_queue,
)
from app.server.live_output import (
    send_reply as _send_reply,
)
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
    context.agent_reply_active = True
    await _send_reply(context, await context.agent.greet())

    pending: list[str] = []
    pending_since: float | None = None
    debounce_s = settings.config.agent.debounce_ms / 1000
    turn_queue: asyncio.Queue[str] = asyncio.Queue()
    turn_worker = asyncio.create_task(_run_turn_queue(context, turn_queue))
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
                    await turn_queue.put(text)
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
            if isinstance(message, SpeechActivityMessage):
                context.user_speaking = message.speaking
                if message.speaking:
                    context.last_user_speech_at = time.monotonic()
                continue
            if isinstance(message, SpeechEventMessage):
                write_event(
                    sweep_dir,
                    Event(
                        t_ms=message.t_ms,
                        type="speech_event",
                        payload={
                            "name": message.name,
                            "detail": message.detail,
                        },
                    ),
                )
                if message.name == "tts-start":
                    context.tts_speaking = True
                    if message.detail == "agent":
                        context.agent_reply_active = True
                elif message.name == "tts-end":
                    context.tts_speaking = False
                    if message.detail == "agent":
                        context.agent_reply_active = False
                elif message.name == "paused":
                    write_event(
                        sweep_dir,
                        Event(
                            t_ms=message.t_ms,
                            type="recognition_paused",
                            payload={"detail": message.detail},
                        ),
                    )
                elif message.name == "resume requested":
                    write_event(
                        sweep_dir,
                        Event(
                            t_ms=message.t_ms,
                            type="recognition_resumed",
                            payload={"detail": message.detail},
                        ),
                    )
                continue
            accepted = _queue_final_text(context, message, pending)
            if accepted:
                cleaned = " ".join(pending)
                context.user_speaking = False
                await websocket.send_json({"type": "user_text_accepted", "text": cleaned})
                if message.forced_final:
                    pending.clear()
                    pending_since = None
                    await turn_queue.put(cleaned)
                elif pending:
                    pending_since = asyncio.get_running_loop().time()
            else:
                cleaned = getattr(context, "last_cleaned_text", "")
                await websocket.send_json({"type": "echo_dropped", "cleaned_text": cleaned})
            if pending and not message.forced_final:
                pending_since = asyncio.get_running_loop().time()
    except WebSocketDisconnect:
        pass
    finally:
        turn_worker.cancel()
        try:
            await turn_worker
        except asyncio.CancelledError:
            pass
        context.websocket = None
        close = getattr(client if "client" in locals() else None, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                logger.exception("Could not close agent model client")


def _queue_final_text(
    context: LiveSessionContext, message: UserTextMessage, pending: list[str]
) -> bool:
    """Discard recent agent echo, otherwise queue a final transcript for debounce."""
    cleaned = context.echo_guard.clean(message.text)
    cleaned_text = cleaned.text
    raw_match = None
    if not cleaned_text and len(message.text.split()) < 4:
        cleaned_text = message.text.strip()
    elif not cleaned_text:
        raw_match = context.echo_guard.match(message.text)
        if raw_match is None:
            cleaned_text = message.text.strip()
    context.last_cleaned_text = cleaned_text
    write_event(
        context.sweep_dir,
        Event(
            t_ms=message.t_ms,
            type="transcript_cleaned",
            payload={
                "original": message.text,
                "cleaned": cleaned_text,
                "removed_words": list(cleaned.removed_words),
            },
        ),
    )
    match = context.echo_guard.match(cleaned_text) or raw_match
    if match is not None:
        write_event(
            context.sweep_dir,
            Event(
                t_ms=message.t_ms,
                type="echo_dropped",
                payload={
                    "text": message.text,
                    "original": message.text,
                    "cleaned": cleaned_text,
                    "matched_line": match.text if match else cleaned.matched_line,
                    "similarity": match.similarity if match else 100,
                },
            ),
        )
        return False
    context.latest_client_t_ms = message.t_ms
    context.last_user_speech_at = time.monotonic()
    pending.append(cleaned_text)
    return True


class _UnavailableLlmClient:
    async def generate(self, **_: object) -> LlmResponse:
        raise RuntimeError("Agent model client is unavailable")
