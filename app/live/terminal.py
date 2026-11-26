"""Run the production agent loop from a developer terminal.

Input is typed user text and environment-backed settings; output is agent speech
text plus tool-call audit lines. Implements the local test flow in docs/06.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import typer
import yaml
from app.live.agent import AgentLoop
from app.live.client import GeminiFlashClient
from app.live.rate_limit import ModelRateLimiter
from app.live.session import LiveSessionContext
from app.live.transcript import TranscriptLine, append_transcript
from app.packet.models import Sweep
from app.pipeline.artifacts import Event
from app.settings import Settings
from app.telemetry.events import write_event


async def run_agent_chat(settings: Settings) -> None:
    """Create a temporary sweep and interact with the production AgentLoop."""
    temporary = tempfile.TemporaryDirectory(prefix="shelfclaim-agent-chat-")
    client: GeminiFlashClient | None = None
    try:
        now = datetime.now().astimezone()
        sweep_id = f"sw_{now:%Y%m%d_%H%M%S}_0000"
        sweep_dir = Path(temporary.name) / sweep_id
        sweep_dir.mkdir(parents=True)
        locale_path = Path("config/locales") / f"{settings.default_country.upper()}.yaml"
        locale = yaml.safe_load(locale_path.read_text(encoding="utf-8"))
        sweep = Sweep(
            id=sweep_id,
            captured_at=now.isoformat(),
            device="agent-chat terminal",
            duration_s=0,
            country=locale["country"],
            currency=locale["currency"],
            locale_config=locale_path.as_posix(),
        )
        (sweep_dir / "sweep.json").write_text(sweep.model_dump_json(indent=2), encoding="utf-8")
        session = LiveSessionContext(sweep_id, sweep_dir)
        limiter = ModelRateLimiter(settings.config.llm)
        client = GeminiFlashClient(settings, limiter)
        agent = AgentLoop(settings, session, client)
        opening = await agent.greet()
        _record_chat_reply(session, opening.text)
        typer.echo(f"Agent: {opening.text}")
        typer.echo("Type /quit to exit. Tool calls and results appear after each turn.")
        event_offset = 0
        while True:
            try:
                user_text = input("You: ").strip()
            except EOFError:
                break
            if user_text.casefold() in {"/quit", "/exit"}:
                break
            if not user_text:
                continue
            reply = await agent.handle_user_text(user_text, None)
            _record_chat_reply(session, reply.text)
            typer.echo(f"Agent: {reply.text}")
            if reply.start_sweep_after_reply:
                await agent.complete_reply(reply)
            event_offset = _print_tool_events(sweep_dir / "events.jsonl", event_offset)
    finally:
        if client is not None:
            await client.close()
        temporary.cleanup()


def _record_chat_reply(session: LiveSessionContext, text: str) -> None:
    append_transcript(
        session.sweep_dir,
        TranscriptLine(t_ms=session.latest_client_t_ms, speaker="agent", text=text),
    )
    write_event(
        session.sweep_dir,
        Event(t_ms=session.latest_client_t_ms, type="transcript_agent", payload={"text": text}),
    )


def _print_tool_events(events_path: Path, offset: int) -> int:
    if not events_path.exists():
        return offset
    lines = events_path.read_text(encoding="utf-8").splitlines()
    for line in lines[offset:]:
        event = json.loads(line)
        if event["type"] in {"tool_call", "tool_result"}:
            label = "Tool call" if event["type"] == "tool_call" else "Tool result"
            typer.echo(f"{label}: {event['payload']}")
        elif event["type"] == "agent_fallback":
            typer.echo(f"Agent fallback: {event['payload']}")
        elif event["type"] == "agent_response_diagnostics":
            typer.echo(f"LLM diagnostics: {event['payload']}")
    return len(lines)
