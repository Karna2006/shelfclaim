"""Define and execute the deterministic tools available to the live agent.

Input is a validated function name and JSON arguments; output is tool data
derived from sweep state or safe stubs. Implements `docs/04_ARCHITECTURE.md` §5.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from app.capture.storage import list_frames
from app.live.models import ToolSchema
from app.packet.models import Sweep, UserStatement
from app.pipeline.artifacts import Event
from app.settings import Settings
from app.telemetry.events import write_event

if TYPE_CHECKING:
    from app.live.session import LiveSessionContext

_STATEMENT_KINDS = {
    "first_edition",
    "signed",
    "rare",
    "print",
    "original",
    "not_mine",
    "exclude_region",
    "correction",
    "ownership",
    "shelf_dimension",
}
_LANDMARK_KINDS = {"ceiling", "corner", "door", "window"}

TOOL_SCHEMAS = [
    ToolSchema(
        name="set_locale",
        description="Set the confirmed country and currency for this sweep.",
        parameters={
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "ISO-2 country code"},
                "currency": {"type": "string", "description": "ISO-4217 currency code"},
            },
            "required": ["country", "currency"],
        },
    ),
    ToolSchema(
        name="start_sweep",
        description="Mark the guided sweep as started after the user is ready.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolSchema(
        name="get_sweep_status",
        description="Return current capture state and known coverage status.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolSchema(
        name="record_user_statement",
        description="Save the user's correction or item statement with the current frame.",
        parameters={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": sorted(_STATEMENT_KINDS)},
                "target_hint": {"type": "string"},
                "text": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["kind", "target_hint", "text"],
        },
    ),
    ToolSchema(
        name="mark_landmark",
        description="Record that a room landmark is visible in the current frame.",
        parameters={
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": sorted(_LANDMARK_KINDS)}},
            "required": ["kind"],
        },
    ),
    ToolSchema(
        name="end_sweep",
        description="Stop capture after the user confirms they are done.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolSchema(
        name="get_packet_summary",
        description="Return the packet summary when the pipeline has produced it.",
        parameters={"type": "object", "properties": {}},
    ),
]


class ToolHandlers:
    """Execute explicit deterministic tools against one sweep folder."""

    def __init__(self, settings: Settings, session: LiveSessionContext) -> None:
        self._settings = settings
        self._session = session

    async def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        """Log a tool call, dispatch its handler, and log the returned facts."""
        timestamp = self._session.latest_client_t_ms
        write_event(
            self._session.sweep_dir,
            Event(t_ms=timestamp, type="tool_call", payload={"name": name, "args": arguments}),
        )
        try:
            result = await self._dispatch(name, arguments)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result = {"error": str(exc)}
        write_event(
            self._session.sweep_dir,
            Event(t_ms=timestamp, type="tool_result", payload={"name": name, "result": result}),
        )
        return result

    async def _dispatch(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        handlers = {
            "set_locale": self._set_locale,
            "start_sweep": self._start_sweep,
            "get_sweep_status": self._get_sweep_status,
            "record_user_statement": self._record_user_statement,
            "mark_landmark": self._mark_landmark,
            "end_sweep": self._end_sweep,
            "get_packet_summary": self._get_packet_summary,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ValueError(f"Unsupported tool: {name}")
        return handler(arguments)

    def _set_locale(self, arguments: dict[str, object]) -> dict[str, object]:
        country = str(arguments["country"]).upper()
        currency = str(arguments["currency"]).upper()
        locale_path = _project_root() / "config" / "locales" / f"{country}.yaml"
        if not locale_path.is_file():
            raise ValueError(f"Unsupported country: {country}")
        locale = yaml.safe_load(locale_path.read_text(encoding="utf-8"))
        if locale.get("currency", "").upper() != currency:
            raise ValueError(f"Unsupported currency {currency} for {country}")
        sweep_path = self._session.sweep_dir / "sweep.json"
        sweep = Sweep.model_validate_json(sweep_path.read_text(encoding="utf-8"))
        updated = sweep.model_copy(update={"country": country, "currency": currency})
        sweep_path.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
        self._session.locale_confirmed = True
        return {"supported": True, "country": country, "currency": currency}

    def _start_sweep(self, _: dict[str, object]) -> dict[str, object]:
        write_event(
            self._session.sweep_dir,
            Event(
                t_ms=self._session.latest_client_t_ms,
                type="stage_started",
                payload={"stage": "capture"},
            ),
        )
        return {"started": True, "sweep_id": self._session.sweep_id}

    def _get_sweep_status(self, _: dict[str, object]) -> dict[str, object]:
        return {
            "capture": "active" if not self._session.capture_stop_requested else "stopping",
            "latest_frame_seq": self._session.latest_capture_seq,
            "coverage": "not yet calculated",
        }

    def _record_user_statement(self, arguments: dict[str, object]) -> dict[str, object]:
        kind = str(arguments["kind"])
        if kind not in _STATEMENT_KINDS:
            raise ValueError(f"Unsupported statement kind: {kind}")
        frame_seq = self._session.latest_capture_seq
        frame_ref = _frame_ref_for_seq(self._session.sweep_dir, frame_seq)
        statements_path = self._session.sweep_dir / "user_statements.jsonl"
        statement = UserStatement(
            id=f"us_{_next_statement_number(statements_path):04d}",
            kind=kind,
            text=self._session.latest_user_text,
            target_hint=str(arguments["target_hint"]),
            value=_user_value(arguments.get("value"), self._session.latest_user_text),
            t_s=max(0, self._session.latest_client_t_ms) / 1000,
            frame_ref=frame_ref,
            frame_seq=frame_seq,
        )
        with statements_path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(statement.model_dump_json() + "\n")
        return {"saved": True, "id": statement.id, "frame_seq": frame_seq}

    def _mark_landmark(self, arguments: dict[str, object]) -> dict[str, object]:
        kind = str(arguments["kind"])
        if kind not in _LANDMARK_KINDS:
            raise ValueError(f"Unsupported landmark: {kind}")
        return {"marked": kind, "frame_seq": self._session.latest_capture_seq}

    def _end_sweep(self, _: dict[str, object]) -> dict[str, object]:
        self._session.capture_stop_requested = True
        sweep_path = self._session.sweep_dir / "sweep.json"
        sweep = Sweep.model_validate_json(sweep_path.read_text(encoding="utf-8"))
        updated = sweep.model_copy(
            update={"duration_s": max(0.0, time_since(self._session.started_at))}
        )
        sweep_path.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return {"stopped": True, "duration_s": updated.duration_s, "stop_capture": True}

    def _get_packet_summary(self, _: dict[str, object]) -> dict[str, object]:
        packet_path = self._session.sweep_dir / "claim_packet.json"
        if not packet_path.is_file():
            return {"ready": False, "totals": None, "review_queue_count": None}
        return {"ready": True, "summary": "Packet summary is available in the claim packet."}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _frame_ref_for_seq(sweep_dir: Path, frame_seq: int | None) -> str | None:
    if frame_seq is None:
        return None
    return next(
        (record.path for record in list_frames(sweep_dir) if record.seq == frame_seq),
        None,
    )


def _next_statement_number(path: Path) -> int:
    if not path.is_file():
        return 1
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) + 1


def _user_value(value: object, transcript: str) -> str | None:
    """Keep a structured user value only when its exact wording was spoken."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip() if value.strip().casefold() in transcript.casefold() else None


def time_since(started_at: float) -> float:
    """Return monotonic elapsed seconds for a capture session."""
    return time.monotonic() - started_at
