"""Record the explicit no-reconstruction choice for the current build.

Input: stage context. Output: `s02_geometry.json` with no metric geometry when
GEOMETRY_BACKEND is off, as required by the current deployment constraints.
"""

from pathlib import Path

from app.pipeline.artifacts import Event, GeometryDoc
from app.pipeline.context import StageContext
from app.telemetry.events import write_event


def run(ctx: StageContext) -> Path:
    """Write an explicit off status instead of fabricating depth or scale."""
    doc = GeometryDoc(
        backend="off",
        status="skipped",
        error="3D reconstruction is out of scope; room and depth dimensions remain unknown.",
    )
    output = ctx.sweep_dir / "s02_geometry.json"
    output.write_text(doc.model_dump_json(indent=2) + "\n", encoding="utf-8")
    write_event(
        ctx.sweep_dir, Event(t_ms=0, type="stage_done", payload={"stage": "s02", "backend": "off"})
    )
    return output
