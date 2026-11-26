"""Run the documented processing stages after capture has ended.

Input: a saved sweep, validated settings and injectable clients. Output: stage
artifacts through S1, S6 or S10; geometry remains explicitly disabled.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.pipeline.artifacts import Event
from app.pipeline.context import StageContext
from app.pipeline.stages import (
    s01_detect,
    s02_geometry,
    s03_books,
    s04_measure,
    s05_transcribe,
    s06_identify,
    s07_price_books,
    s08_items,
    s09_room,
    s10_assemble,
)
from app.settings import Settings
from app.telemetry.events import write_event
from app.telemetry.ledger import Ledger

_ORDER = ("s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10")


async def run_pipeline(
    sweep_dir: Path,
    settings: Settings,
    *,
    from_stage: str = "s01",
    until: str = "s10",
    price_limit: int = 10,
    max_keyframes: int | None = None,
    frame_seqs: tuple[int, ...] | None = None,
    max_books: int | None = None,
    clients: dict[str, object] | None = None,
) -> Path:
    """Run each stage once in order and update latency telemetry after completion."""
    if from_stage not in _ORDER:
        raise ValueError(f"Unsupported starting stage: {from_stage}")
    if until not in _ORDER:
        raise ValueError(f"Unsupported pipeline stage: {until}")
    if _ORDER.index(from_stage) > _ORDER.index(until):
        raise ValueError("Starting stage must not follow the ending stage")
    if max_keyframes is not None and max_keyframes < 1:
        raise ValueError("max_keyframes must be positive")
    if max_books is not None and max_books < 1:
        raise ValueError("max_books must be positive")
    selected_settings = settings.model_copy(update={"geometry_backend": "off"})
    context = StageContext(sweep_dir, selected_settings, Ledger(), clients or {})
    started = time.perf_counter()
    output = sweep_dir / "sweep.json"
    stage_functions: dict[str, Any] = {
        "s01": lambda ctx: s01_detect.run(ctx, max_keyframes=max_keyframes, frame_seqs=frame_seqs),
        "s02": s02_geometry.run,
        "s03": s03_books.run,
        "s04": s04_measure.run,
        "s05": lambda ctx: s05_transcribe.run(ctx, max_books=max_books),
        "s06": lambda ctx: s06_identify.run(ctx, max_books=max_books),
        "s07": lambda ctx: s07_price_books.run(ctx, limit=price_limit),
        "s08": s08_items.run,
        "s09": s09_room.run,
        "s10": s10_assemble.run,
    }
    stages = list(_ORDER[_ORDER.index(from_stage) : _ORDER.index(until) + 1])
    if from_stage == "s01" and until != "s01" and (sweep_dir / "s01_detections.json").is_file():
        stages.remove("s01")
    for stage in stages:
        write_event(
            sweep_dir,
            Event(t_ms=0, type="stage_started", payload={"stage": stage, "backend": "off"}),
        )
        try:
            with context.ledger.stage(stage):
                stage_output = stage_functions[stage](context)
                output = await stage_output if asyncio.iscoroutine(stage_output) else stage_output
        except Exception as exc:
            write_event(
                sweep_dir,
                Event(
                    t_ms=0,
                    type="error",
                    payload={
                        "stage": stage,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    },
                ),
            )
            raise
    _write_telemetry(sweep_dir, context.ledger.to_dict(), time.perf_counter() - started)
    _update_packet_telemetry(sweep_dir, context.ledger.to_dict(), time.perf_counter() - started)
    return output


def _write_telemetry(sweep_dir: Path, ledger: dict[str, Any], elapsed: float) -> None:
    payload = {
        "stages": ledger.get("stages", {}),
        "costs": ledger.get("costs", []),
        "total_cost_usd": ledger.get("total_cost_usd"),
        "time_to_packet_s": round(elapsed, 6),
    }
    (sweep_dir / "telemetry.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _update_packet_telemetry(sweep_dir: Path, ledger: dict[str, Any], elapsed: float) -> None:
    path = sweep_dir / "claim_packet.json"
    if not path.is_file():
        return
    packet = json.loads(path.read_text(encoding="utf-8"))
    packet["meta"]["telemetry"] = {
        **ledger,
        "time_to_packet_s": round(elapsed, 6),
        "costs": ledger.get("costs", []),
    }
    path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
