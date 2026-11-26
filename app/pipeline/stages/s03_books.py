"""Build fallback shelf rows and best-frame book counts from S1 boxes.

Input: saved frame metrics and S1 detections. Output: `s03_books_raw.json`;
counts are deterministic post-NMS box counts as specified in architecture §3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.capture.storage import list_frames
from app.pipeline.artifacts import Detection, DetectionsDoc, Event, FrameRecord
from app.pipeline.context import StageContext
from app.telemetry.events import write_event


def run(ctx: StageContext) -> Path:
    """Write shelf unit/row structure using only saved S1 detections."""
    detections_path = ctx.sweep_dir / "s01_detections.json"
    if not detections_path.is_file():
        raise FileNotFoundError("S1 detections are required before book counting")
    detections = DetectionsDoc.model_validate_json(detections_path.read_text(encoding="utf-8"))
    result = build_book_clusters(
        list_frames(ctx.sweep_dir),
        detections,
        full_width_pct=ctx.settings.config.structure.full_row_width_pct,
        disagreement_pct=ctx.settings.config.review.row_count_disagreement_pct,
    )
    output = ctx.sweep_dir / "s03_books_raw.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_event(
        ctx.sweep_dir,
        Event(t_ms=0, type="stage_done", payload={"stage": "s03", "books": len(result["books"])}),
    )
    return output


def build_book_clusters(
    frames: list[FrameRecord],
    detections: DetectionsDoc,
    *,
    full_width_pct: float = 0.80,
    disagreement_pct: float = 0.10,
) -> dict[str, Any]:
    """Choose sharpest full-row frames, count post-NMS spines, and keep candidates."""
    frame_by_seq = {frame.seq: frame for frame in frames}
    units: dict[str, dict[int, dict[str, Any]]] = {}
    books: list[dict[str, Any]] = []
    for seq, rows in sorted(detections.frames.items()):
        frame = frame_by_seq.get(seq)
        if frame is None:
            continue
        shelf_boxes = [box for box in rows if box.cls == "shelf_unit"]
        shelf_boxes.sort(key=lambda box: box.box_px.x)
        for unit_index, unit_box in enumerate(shelf_boxes):
            unit_name = _unit_name(unit_index)
            unit = unit_box.box_px
            boards = [
                box
                for box in rows
                if box.cls == "shelf_board" and _horizontal_overlap(box, unit_box) >= full_width_pct
            ]
            board_bands = _board_bands(boards)
            spines = [box for box in rows if box.cls in {"book_spine", "book_stack"}]
            for row_number, (top, bottom) in enumerate(
                zip(board_bands, board_bands[1:], strict=False), 1
            ):
                midpoint = (top[1] + bottom[0]) / 2
                row_spines = [
                    spine
                    for spine in spines
                    if unit.x <= _center_x(spine) <= unit.x + unit.w
                    and top[1] <= _center_y(spine) < bottom[0]
                ]
                entry = units.setdefault(unit_name, {}).setdefault(
                    row_number,
                    {
                        "candidates": [],
                        "best": None,
                        "z_min": top[1] / frame.h,
                        "z_max": bottom[0] / frame.h,
                    },
                )
                entry["candidates"].append({"seq": seq, "count": len(row_spines)})
                current = entry["best"]
                if current is None or (frame.blur or -1) > current["sharpness"]:
                    entry["best"] = {
                        "seq": seq,
                        "sharpness": frame.blur or 0,
                        "spines": sorted(row_spines, key=_center_x),
                        "center_y": midpoint,
                    }
    review: list[dict[str, str]] = []
    unit_docs = []
    for unit_name, rows in units.items():
        row_docs = []
        for row_number, entry in sorted(rows.items()):
            candidates = entry["candidates"]
            best = entry["best"]
            counts = [item["count"] for item in candidates]
            if (
                counts
                and max(counts) > 0
                and (max(counts) - min(counts)) / max(counts) > disagreement_pct
            ):
                review.append(
                    {"ref_id": f"{unit_name}-{row_number}", "code": "count_disagreement_row"}
                )
            if best is None:
                continue
            row_docs.append(
                {
                    "row": row_number,
                    "z_min": entry["z_min"],
                    "z_max": entry["z_max"],
                    "candidate_counts": candidates,
                    "count": len(best["spines"]),
                    "best_frame_seq": best["seq"],
                }
            )
            for position, detection in enumerate(best["spines"], 1):
                books.append(
                    {
                        "book_id": f"b_{len(books) + 1:04d}",
                        "unit": unit_name,
                        "row": row_number,
                        "position": position,
                        "member_dets": [detection.det_id],
                        "best_view": {
                            "seq": best["seq"],
                            "frame_ref": frame_by_seq[best["seq"]].path,
                            "bbox": detection.box_px.model_dump(),
                            "unit_bbox": unit.model_dump(),
                        },
                        "count_method": "best_frame",
                    }
                )
        unit_docs.append({"unit": unit_name, "rows": row_docs})
    return {"units": unit_docs, "books": books, "review_queue": review}


def _unit_name(index: int) -> str:
    """Convert a zero-based order into spreadsheet-style shelf labels."""
    label = ""
    while index >= 0:
        index, remainder = divmod(index, 26)
        label = chr(65 + remainder) + label
        index -= 1
    return label


def _center_x(box: Detection) -> float:
    return box.box_px.x + box.box_px.w / 2


def _center_y(box: Detection) -> float:
    return box.box_px.y + box.box_px.h / 2


def _horizontal_overlap(board: Detection, unit: Detection) -> float:
    left = max(board.box_px.x, unit.box_px.x)
    right = min(board.box_px.x + board.box_px.w, unit.box_px.x + unit.box_px.w)
    return max(0, right - left) / max(1, unit.box_px.w)


def _board_bands(boards: list[Detection]) -> list[tuple[float, float]]:
    ordered = sorted(boards, key=_center_y)
    groups: list[list[Detection]] = []
    for board in ordered:
        if groups and abs(_center_y(board) - _center_y(groups[-1][0])) <= max(4, board.box_px.h):
            groups[-1].append(board)
        else:
            groups.append([board])
    return [
        (min(item.box_px.y for item in group), max(item.box_px.y + item.box_px.h for item in group))
        for group in groups
    ]
