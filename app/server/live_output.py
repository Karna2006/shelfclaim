"""Send agent replies and capture cues to the active browser session.

Input: per-sweep session state and normalized agent or monitor output. Output:
WebSocket messages, transcript lines, and delivery telemetry for docs/04 §4.3, §5.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from app.live.agent import FALLBACK_LINE
from app.live.models import AgentReply
from app.live.session import LiveSessionContext
from app.live.transcript import TranscriptLine, append_transcript
from app.pipeline.artifacts import Event
from app.settings import Settings
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
    await _send_phone(
        context, {"type": "agent_text", "text": reply.text, "t_ms": context.latest_client_t_ms}
    )
    await _publish_viewer_caption(context, "agent", reply.text)
    if reply.start_sweep_after_reply and context.agent is not None:
        await context.agent.complete_reply(reply)
    if reply.stop_capture:
        await _publish_message(context, {"type": "control", "action": "stop_capture"})
        _start_finalization(context)


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
    await _send_phone(context, {"type": "cue", "text": cue, "priority": priority, "kind": kind})
    await _publish_viewer_caption(context, "cue", cue)
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
        await _send_phone(
            context,
            {"type": "agent_text", "text": text, "t_ms": context.latest_client_t_ms},
        )
        await _publish_viewer_caption(context, "agent", text)


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


async def _send_phone(context: LiveSessionContext, message: dict[str, object]) -> None:
    if context.websocket is not None:
        await context.websocket.send_json(message)


async def _publish_viewer_caption(context: LiveSessionContext, speaker: str, text: str) -> None:
    await _publish_viewer(
        context,
        {"type": "caption", "speaker": speaker, "text": text, "t_ms": context.latest_client_t_ms},
    )


async def _publish_viewer(context: LiveSessionContext, message: dict[str, object]) -> None:
    hub = context.viewer_hub
    if hub is None:
        websocket = context.websocket
        app = getattr(websocket, "app", None) if websocket is not None else None
        hub = getattr(getattr(app, "state", None), "viewer_hub", None)
    if hub is not None:
        await hub.publish(context.sweep_id, message)


async def _publish_message(context: LiveSessionContext, message: dict[str, object]) -> None:
    await _send_phone(context, message)
    await _publish_viewer(context, message)


def _start_finalization(context: LiveSessionContext) -> None:
    task = context.finalization_task
    if task is not None and not task.done():
        return
    websocket = context.websocket
    app = getattr(websocket, "app", None) if websocket is not None else None
    settings = getattr(getattr(app, "state", None), "settings", None)
    if settings is None:
        return
    context.finalization_task = asyncio.create_task(_finalize_sweep(context, settings))


async def _finalize_sweep(context: LiveSessionContext, settings: Settings) -> None:
    """Run the same pipeline as CLI replay and stream each stage's progress."""
    from app.pipeline.orchestrator import run_pipeline

    main_loop = asyncio.get_running_loop()

    try:

        def run_pipeline_in_worker() -> Path:
            async def on_progress(progress: dict[str, object]) -> None:
                future = asyncio.run_coroutine_threadsafe(
                    _broadcast_progress(context, progress), main_loop
                )
                await asyncio.wrap_future(future)

            return asyncio.run(run_pipeline(context.sweep_dir, settings, on_progress=on_progress))

        await asyncio.to_thread(run_pipeline_in_worker)
        await _publish_message(context, _inventory_message(context.sweep_dir, finalized=True))
        if context.agent is not None:
            summary = await context.agent.tools.execute("get_packet_summary", {})
            if not summary.get("ready"):
                raise RuntimeError("Pipeline completed without a packet summary")
            text = _summary_text(summary)
            await send_reply(context, AgentReply(text=text))
        else:
            await _send_phone(
                context,
                {"type": "agent_text", "text": "Done. The report is ready."},
            )
            await _publish_viewer_caption(context, "agent", "Done. The report is ready.")
        context.packet_ready_sent = True
        await _publish_message(
            context,
            {"type": "packet_ready", "report_url": f"/sweeps/{context.sweep_id}/"},
        )
    except Exception as exc:
        write_event(
            context.sweep_dir,
            Event(
                t_ms=context.latest_client_t_ms,
                type="error",
                payload={
                    "stage": "finalization",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                },
            ),
        )
        logger.exception("Sweep finalization failed for %s", context.sweep_id)
        await _publish_message(
            context,
            {
                "type": "pipeline_progress",
                "stage": "finalization",
                "state": "failed",
            },
        )
        await send_reply(context, AgentReply(text="I couldn't finish the report; it's logged."))


async def _broadcast_progress(context: LiveSessionContext, progress: dict[str, object]) -> None:
    await _publish_message(context, {"type": "pipeline_progress", **progress})
    if progress.get("state") == "complete" and progress.get("stage") in {"s03", "s08"}:
        await _publish_message(context, _inventory_message(context.sweep_dir))


def _summary_text(summary: dict[str, object]) -> str:
    count = summary.get("book_count")
    identified = summary.get("books_identified")
    if _is_count(count) and _is_count(identified):
        return f"Done. I found {count} books, {identified} identified. The report is ready."
    return "Done. The report is ready."


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _inventory_message(sweep_dir: Path, *, finalized: bool = False) -> dict[str, object]:
    root = sweep_dir
    books: dict[str, object] = {"rows": [], "items": [], "provisional": not finalized}
    book_path = root / "s03_books_raw.json"
    if book_path.is_file():
        raw = json.loads(book_path.read_text(encoding="utf-8"))
        books["rows"] = [
            {"row": f"{unit['unit']}-{row['row']}", "count": row.get("count")}
            for unit in raw.get("units", [])
            for row in unit.get("rows", [])
        ]
    item_path = root / ("claim_packet.json" if finalized else "s08_items.json")
    if item_path.is_file():
        raw = json.loads(item_path.read_text(encoding="utf-8"))
        items = raw.get("items", [])
        books["items"] = [
            {"category": item.get("category", "item"), "description": item.get("description", "")}
            for item in items
        ]
    return {"type": "inventory", **books}
