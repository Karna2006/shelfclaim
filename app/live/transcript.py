"""Append validated user, agent, and cue lines to a sweep transcript.

Input is one transcript turn and timestamp; output is a JSONL record in the
sweep folder. Implements transcript evidence in `docs/05_DATA_SCHEMA.md` §2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import orjson
from pydantic import BaseModel, ConfigDict, Field


class TranscriptLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_ms: int = Field(ge=0)
    speaker: Literal["user", "agent", "cue"]
    text: str = Field(min_length=1)
    final: bool = True
    recorded_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def append_transcript(sweep_dir: Path, line: TranscriptLine) -> None:
    """Append a line without including keys or raw microphone data."""
    with (sweep_dir / "transcript.jsonl").open("ab") as stream:
        stream.write(orjson.dumps(line.model_dump(mode="json")) + b"\n")
