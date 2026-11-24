"""Append and read structured sweep events.

Input: validated Event models. Output: one JSON object per line in
`events.jsonl`, written atomically per record. Implements `docs/05_DATA_SCHEMA.md` §2.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import orjson
from app.pipeline.artifacts import Event


def write_event(sweep_dir: Path, event: Event) -> None:
    """Append a validated event without logging payloads that may contain secrets."""
    event_path = sweep_dir / "events.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("ab") as stream:
        stream.write(orjson.dumps(event.model_dump(mode="json")) + b"\n")


def iter_events(path: Path) -> Iterator[Event]:
    """Yield valid event records from a JSONL file."""
    if not path.exists():
        return
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line.strip():
                try:
                    yield Event.model_validate(orjson.loads(line))
                except (orjson.JSONDecodeError, ValueError) as exc:
                    raise ValueError(f"Invalid event at {path}:{line_number}") from exc
