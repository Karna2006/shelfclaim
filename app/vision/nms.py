"""Consolidate same-frame detector duplicates using rotated-box overlap.

Input: pixel detections and configured thresholds. Output: kept detections with
suppressed IDs and review flags, following architecture §1 NMS rules.
"""

from __future__ import annotations

import math

import cv2
from app.pipeline.artifacts import Detection
from app.settings import DedupSettings


def suppress_frame_duplicates(
    detections: list[Detection], settings: DedupSettings
) -> list[Detection]:
    """Merge highly overlapping boxes and flag borderline pairs per configured rules."""
    kept: list[Detection] = []
    suppressed: set[str] = set()
    merges: dict[str, list[str]] = {}
    borderline: set[str] = set()
    by_class: dict[str, list[Detection]] = {}
    for item in detections:
        by_class.setdefault(item.cls, []).append(item)
    for group in by_class.values():
        group.sort(key=lambda item: _rank(item), reverse=True)
        for index, first in enumerate(group):
            if first.det_id in suppressed:
                continue
            for second in group[index + 1 :]:
                if second.det_id in suppressed:
                    continue
                iou, containment, center_ratio = _overlap(first, second)
                merge = iou >= settings.within_frame_iou or (
                    containment >= settings.within_frame_containment
                    and center_ratio < settings.within_frame_center_factor
                )
                if merge:
                    suppressed.add(second.det_id)
                    merges.setdefault(first.det_id, []).append(second.det_id)
                elif iou >= settings.within_frame_review_iou_min:
                    borderline.update((first.det_id, second.det_id))
    for item in detections:
        if item.det_id in suppressed:
            continue
        flags = list(item.flags)
        if item.det_id in borderline:
            flags.append("possible_duplicate_box")
        kept.append(
            item.model_copy(
                update={"merged_from": merges.get(item.det_id, item.merged_from), "flags": flags}
            )
        )
    return kept


def _rank(item: Detection) -> tuple[float, int]:
    box = item.box_px
    return (item.score if item.score is not None else 0, box.w * box.h)


def _overlap(first: Detection, second: Detection) -> tuple[float, float, float]:
    a, b = first.box_px, second.box_px
    rect_a = ((a.x + a.w / 2, a.y + a.h / 2), (a.w, a.h), a.angle_deg)
    rect_b = ((b.x + b.w / 2, b.y + b.h / 2), (b.w, b.h), b.angle_deg)
    result, points = cv2.rotatedRectangleIntersection(rect_a, rect_b)
    intersection = 0.0
    if points is not None and len(points) >= 3:
        intersection = abs(cv2.contourArea(cv2.convexHull(points)))
    area_a, area_b = a.w * a.h, b.w * b.h
    union = area_a + area_b - intersection
    iou = intersection / union if union else 0.0
    smaller = min(area_a, area_b)
    containment = intersection / smaller if smaller else 0.0
    short_side = max(1, min(a.w, a.h, b.w, b.h))
    center = math.hypot(a.x + a.w / 2 - b.x - b.w / 2, a.y + a.h / 2 - b.y - b.h / 2)
    return iou, containment, center / short_side
