"""Write null room measurements because reconstruction is disabled.

Input: saved sweep detections and the geometry-backend choice. Output:
`s09_room.json` with unknown dimensions rather than unsupported area estimates.
"""

from pathlib import Path

from app.pipeline.artifacts import Event, RoomDoc
from app.pipeline.context import StageContext
from app.telemetry.events import write_event


def run(ctx: StageContext) -> Path:
    """Persist the explicitly unmeasured room artifact required by S10."""
    doc = RoomDoc(
        room={
            "length_m": None,
            "width_m": None,
            "height_m": None,
            "floor_area_m2": None,
            "wall_area_m2": None,
            "shelved_wall_area_m2": None,
            "scale_method": "not measured (3D reconstruction out of scope for this build)",
            "confidence": 0,
            "shape": None,
            "coverage_pct": None,
        },
        planes={},
        point_count=None,
    )
    output = ctx.sweep_dir / "s09_room.json"
    output.write_text(doc.model_dump_json(indent=2) + "\n", encoding="utf-8")
    write_event(ctx.sweep_dir, Event(t_ms=0, type="stage_done", payload={"stage": "s09"}))
    return output
