"""Measure spine boxes against same-frame ArUco marker planes.

Input: S3 best views and capture-time marker corners. Output: S4 dimensions,
nulls and review reasons where scale evidence is absent, per architecture §4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from app.capture.storage import list_frames
from app.packet.models import BBox
from app.pipeline.artifacts import Event
from app.pipeline.context import StageContext
from app.telemetry.events import write_event


def run(ctx: StageContext) -> Path:
    """Write best-view dimensions using only same-frame markers."""
    source = ctx.sweep_dir / "s03_books_raw.json"
    if not source.is_file():
        raise FileNotFoundError("S3 book clusters are required before measurement")
    raw = json.loads(source.read_text(encoding="utf-8"))
    frames = {frame.seq: frame for frame in list_frames(ctx.sweep_dir)}
    result = measure_books(
        raw,
        frames,
        ctx.settings.marker_size_mm,
        ctx.settings.config.measure.height_range_cm,
        ctx.settings.config.measure.thickness_range_cm,
    )
    output = ctx.sweep_dir / "s04_measurements.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_event(ctx.sweep_dir, Event(t_ms=0, type="stage_done", payload={"stage": "s04"}))
    return output


def measure_books(
    raw: dict[str, Any],
    frames: dict[int, Any],
    marker_size_mm: float,
    height_range_cm: tuple[float, float],
    thickness_range_cm: tuple[float, float],
) -> dict[str, Any]:
    """Map each best-view box onto an ArUco plane when its frame has a marker."""
    books: dict[str, dict[str, Any]] = {}
    review: list[dict[str, str]] = []
    row_spans: dict[str, list[float]] = {}
    for book in raw.get("books", []):
        view = book["best_view"]
        seq = int(view["seq"])
        frame = frames.get(seq)
        bbox = BBox.model_validate(view["bbox"])
        unit_bbox = BBox.model_validate(view["unit_bbox"])
        marker = _marker_inside(frame, unit_bbox) if frame is not None else None
        dimensions = measure_spine_bbox(bbox, marker.corners, marker_size_mm) if marker else None
        book_id = str(book["book_id"])
        if dimensions is None:
            books[book_id] = {
                "height_cm": None,
                "thickness_cm": None,
                "method": "none",
                "flags": [],
            }
            review.append({"ref_id": book_id, "code": "missing_scale_marker"})
            continue
        height_cm, thickness_cm = dimensions
        flags = []
        if not height_range_cm[0] <= height_cm <= height_range_cm[1]:
            flags.append("height_outlier")
        if not thickness_range_cm[0] <= thickness_cm <= thickness_range_cm[1]:
            flags.append("thickness_outlier")
        books[book_id] = {
            "height_cm": height_cm,
            "thickness_cm": thickness_cm,
            "method": "marker_plane",
            "flags": flags,
        }
        row_key = f"{book['unit']}-{book['row']}:{seq}"
        plane_x = _bbox_plane_x(bbox, marker.corners, marker_size_mm)
        row_spans.setdefault(row_key, []).extend(plane_x)
    measurable = [max(points) - min(points) for points in row_spans.values()]
    return {
        "books": books,
        "rows": {},
        "shelf_run_m": sum(measurable) / 100 if measurable else None,
        "sum_thickness_m": None,
        "review_queue": review,
    }


def measure_spine_bbox(
    bbox: BBox, marker_corners: list[tuple[float, float]], marker_size_mm: float
) -> tuple[float, float] | None:
    """Return long and short box dimensions in centimetres from a marker homography."""
    if len(marker_corners) != 4 or marker_size_mm <= 0:
        return None
    mapped = _map_box(bbox, marker_corners, marker_size_mm)
    if mapped is None:
        return None
    sides = [float(np.linalg.norm(mapped[index] - mapped[(index + 1) % 4])) for index in range(4)]
    if not sides or not all(np.isfinite(value) for value in sides):
        return None
    return round(max(sides) / 10, 2), round(min(sides) / 10, 2)


def _bbox_plane_x(
    bbox: BBox, marker_corners: list[tuple[float, float]], marker_size_mm: float
) -> list[float]:
    mapped = _map_box(bbox, marker_corners, marker_size_mm)
    return [float(value) for value in mapped[:, 0]] if mapped is not None else []


def _map_box(
    bbox: BBox, marker_corners: list[tuple[float, float]], marker_size_mm: float
) -> np.ndarray | None:
    if len(marker_corners) != 4 or marker_size_mm <= 0:
        return None
    source = np.asarray(marker_corners, dtype=np.float32)
    target = np.asarray(
        [[0, 0], [marker_size_mm, 0], [marker_size_mm, marker_size_mm], [0, marker_size_mm]],
        dtype=np.float32,
    )
    homography = cv2.getPerspectiveTransform(source, target)
    center = (bbox.x + bbox.w / 2, bbox.y + bbox.h / 2)
    corners = cv2.boxPoints((center, (bbox.w, bbox.h), bbox.angle_deg)).astype(np.float32)
    mapped = cv2.perspectiveTransform(corners.reshape(1, -1, 2), homography).reshape(-1, 2)
    return mapped if np.isfinite(mapped).all() else None


def _marker_inside(frame: Any, unit: BBox) -> Any | None:
    if frame is None:
        return None
    for marker in frame.markers:
        xs = [point[0] for point in marker.corners]
        ys = [point[1] for point in marker.corners]
        if not xs:
            continue
        center_x, center_y = sum(xs) / len(xs), sum(ys) / len(ys)
        if unit.x <= center_x <= unit.x + unit.w and unit.y <= center_y <= unit.y + unit.h:
            return marker
    return None
