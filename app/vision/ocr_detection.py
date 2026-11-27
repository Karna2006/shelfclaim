"""Turn frame OCR into deterministic spine boxes.

Input: confident RapidOCR lines in original-frame coordinates. Output: row
bands and one tall spine detection per horizontal text cluster, per docs/04 S1.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from app.packet.models import BBox
from app.pipeline.artifacts import Detection
from app.vision.local_ocr import FrameOcrLine


@dataclass(frozen=True)
class OcrSpineCluster:
    row_index: int
    box: BBox
    lines: tuple[FrameOcrLine, ...]
    confidence: float


def cluster_ocr_lines(
    lines: Sequence[FrameOcrLine],
    width: int,
    height: int,
    *,
    confidence_min: float = 0.5,
    min_spine_height_pct: float = 0.08,
    vertical_aspect_min: float = 1.0,
    flat_line_width_pct: float = 0.08,
    row_gap_factor: float = 0.6,
    x_eps_factor: float = 0.6,
    max_cluster_width_pct_row: float = 0.45,
) -> list[OcrSpineCluster]:
    """Cluster lines into rows by y gaps, then books by x distance within each row."""
    short_side = min(width, height)
    minimum_spine_height = short_side * min_spine_height_pct
    vertical_lines = [
        line
        for line in lines
        if line.confidence >= confidence_min
        and line.rotation in {90, 270}
        and line.h >= minimum_spine_height
        and line.h >= line.w * vertical_aspect_min
    ]
    minimum_flat_width = short_side * flat_line_width_pct
    usable = vertical_lines + [
        line
        for line in lines
        if line.confidence >= confidence_min
        and line.rotation == 0
        and line.w >= minimum_flat_width
        and vertical_lines
    ]
    if not usable:
        return []

    median_box_height = median(line.h for line in usable)
    row_gap = max(1.0, row_gap_factor * median_box_height)
    row_groups: list[list[FrameOcrLine]] = []
    for line in sorted(usable, key=lambda item: (item.center[1], item.center[0], item.text)):
        if row_groups and line.center[1] - row_groups[-1][-1].center[1] <= row_gap:
            row_groups[-1].append(line)
        else:
            row_groups.append([line])

    output: list[OcrSpineCluster] = []
    for row_index, group in enumerate(row_groups, start=1):
        row_top = max(0.0, min(line.y for line in group))
        row_bottom = min(float(height), max(line.y + line.h for line in group))
        line_height = (
            median(line.ocr_height for line in group if line.ocr_height > 0)
            if any(line.ocr_height > 0 for line in group)
            else median(line.w for line in group)
        )
        x_eps = max(1.0, x_eps_factor * line_height)
        max_x_span = max(x_eps, (row_bottom - row_top) * max_cluster_width_pct_row)
        x_groups = _cluster_by_x(group, x_eps, max_x_span)
        for spine_lines in x_groups:
            x0 = max(0, int(min(line.x for line in spine_lines)))
            x1 = min(width, int(max(line.x + line.w for line in spine_lines) + 0.999))
            y0, y1 = int(row_top), int(row_bottom + 0.999)
            if x1 <= x0 or y1 <= y0:
                continue
            ordered = tuple(sorted(spine_lines, key=lambda item: (item.center[1], item.text)))
            vertical = sum(line.rotation in {90, 270} for line in ordered)
            angle = 90.0 if vertical >= len(ordered) / 2 else 0.0
            output.append(
                OcrSpineCluster(
                    row_index=row_index,
                    box=BBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0, angle_deg=angle),
                    lines=ordered,
                    confidence=sum(line.confidence for line in ordered) / len(ordered),
                )
            )
    return sorted(output, key=lambda item: (item.row_index, item.box.x, item.box.y))


def detections_from_ocr(
    seq: int,
    lines: Sequence[FrameOcrLine],
    width: int,
    height: int,
    *,
    confidence_min: float,
    min_spine_height_pct: float,
    vertical_aspect_min: float,
    flat_line_width_pct: float,
    row_gap_factor: float,
    x_eps_factor: float,
    max_cluster_width_pct_row: float,
) -> list[Detection]:
    """Create stable S1 IDs and preserve the text lines for S5."""
    clusters = cluster_ocr_lines(
        lines,
        width,
        height,
        confidence_min=confidence_min,
        min_spine_height_pct=min_spine_height_pct,
        vertical_aspect_min=vertical_aspect_min,
        flat_line_width_pct=flat_line_width_pct,
        row_gap_factor=row_gap_factor,
        x_eps_factor=x_eps_factor,
        max_cluster_width_pct_row=max_cluster_width_pct_row,
    )
    return [
        Detection(
            det_id=f"f{seq:06d}_ocr{index:04d}",
            cls="book_spine",
            box_px=cluster.box,
            score=cluster.confidence,
            row_index=cluster.row_index,
            ocr_lines=[
                {
                    "text": line.text,
                    "confidence": line.confidence,
                    "bbox": {"x": line.x, "y": line.y, "w": line.w, "h": line.h},
                    "rotation": line.rotation,
                }
                for line in cluster.lines
            ],
        )
        for index, cluster in enumerate(clusters)
    ]


def _cluster_by_x(
    lines: Sequence[FrameOcrLine], epsilon: float, max_span: float
) -> list[list[FrameOcrLine]]:
    ordered = sorted(lines, key=lambda item: (item.center[0], item.center[1], item.text))
    groups: list[list[FrameOcrLine]] = []
    for line in ordered:
        fits_gap = groups and line.center[0] - groups[-1][-1].center[0] <= epsilon
        fits_span = groups and line.center[0] - groups[-1][0].center[0] <= max_span
        if fits_gap and fits_span:
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups
