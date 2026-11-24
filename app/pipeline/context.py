"""Dependencies passed to a single pipeline stage.

Input: sweep directory, validated settings and per-run services. Output: a
mutable context scoped to one sweep, not process-global state. Implements `AGENTS.md` §2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.settings import Settings
from app.telemetry.ledger import Ledger


@dataclass(slots=True)
class StageContext:
    sweep_dir: Path
    settings: Settings
    ledger: Ledger
    clients: dict[str, object] = field(default_factory=dict)
