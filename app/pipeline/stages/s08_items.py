"""Deduplicate visible non-book item detections without 3D reconstruction.

Input: S1 item boxes, best-frame quality and saved images. Output: S8 item rows
with null dimensions and appraisal review until item pricing evidence exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.capture.storage import list_frames
from app.pipeline.artifacts import DetectionsDoc, Event, ItemsDoc
from app.pipeline.context import StageContext
from app.telemetry.events import write_event


def run(ctx: StageContext) -> Path:
    """Create provisional item rows, deduplicated by category and frame proximity."""
    detection_path = ctx.sweep_dir / "s01_detections.json"
    if not detection_path.is_file():
        raise FileNotFoundError("S1 detections are required before item discovery")
    detections = DetectionsDoc.model_validate_json(detection_path.read_text(encoding="utf-8"))
    frames = {frame.seq: frame for frame in list_frames(ctx.sweep_dir)}
    candidates = []
    for seq, boxes in detections.frames.items():
        frame = frames.get(seq)
        if frame is None:
            continue
        for box in boxes:
            if box.cls != "item" or box.item_category in {"shelving", "other"}:
                continue
            candidates.append((frame, box))
    candidates.sort(key=lambda pair: pair[0].t_ms)
    groups: list[list[tuple[Any, Any]]] = []
    for candidate in candidates:
        frame, box = candidate
        category = box.item_category or "other"
        center = _center(box)
        threshold = max(frame.w, frame.h) * ctx.settings.config.dedup.item_frame_proximity_fraction
        group = next(
            (
                item_group
                for item_group in groups
                if item_group[-1][1].item_category == category
                and _distance(center, _center(item_group[-1][1])) <= threshold
            ),
            None,
        )
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    items = []
    for index, group in enumerate(groups, 1):
        frame, box = max(group, key=lambda pair: pair[0].blur or -1)
        category = box.item_category or "other"
        is_artwork = category in {"framed_art", "portrait"}
        items.append(
            {
                "item_id": f"i_{index:04d}",
                "category": category,
                "member_dets": [member.det_id for _, member in group],
                "best_view": {
                    "seq": frame.seq,
                    "frame_ref": frame.path,
                    "bbox": box.box_px.model_dump(),
                },
                "dimensions_cm": {"w": None, "h": None, "d": None},
                "dims_method": "none",
                "description": category.replace("_", " "),
                "brand_model": "",
                "material": None,
                "is_artwork": is_artwork,
                "status": "needs_appraisal",
                "confidence": box.score,
            }
        )
    output = ctx.sweep_dir / "s08_items.json"
    output.write_text(ItemsDoc(items=items).model_dump_json(indent=2) + "\n", encoding="utf-8")
    write_event(
        ctx.sweep_dir,
        Event(t_ms=0, type="stage_done", payload={"stage": "s08", "items": len(items)}),
    )
    return output


def _center(detection: Any) -> tuple[float, float]:
    box = detection.box_px
    return box.x + box.w / 2, box.y + box.h / 2


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5
