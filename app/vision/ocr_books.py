"""Build stable book tracks from OCR spine boxes across coverage frames.

Input: S1 OCR detections and frame QC records. Output: deterministic S3 rows,
books, candidate counts and evidence views without geometric reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.packet.models import BBox
from app.pipeline.artifacts import Detection, DetectionsDoc, FrameRecord


@dataclass
class _Track:
    row_index: int
    detections: list[tuple[FrameRecord, Detection]] = field(default_factory=list)


def build_ocr_book_clusters(
    frames: list[FrameRecord],
    detections: DetectionsDoc,
    *,
    max_gap_ms: int,
    min_x_overlap: float,
    disagreement_pct: float,
) -> dict[str, Any]:
    """Merge close-in-time same-row boxes whose horizontal positions overlap."""
    frame_by_seq = {frame.seq: frame for frame in frames}
    tracks_by_row: dict[int, list[_Track]] = {}
    counts_by_row: dict[int, list[dict[str, int]]] = {}
    for seq, boxes in sorted(detections.frames.items()):
        frame = frame_by_seq.get(seq)
        if frame is None:
            continue
        row_boxes: dict[int, list[Detection]] = {}
        for box in boxes:
            if box.cls == "book_spine" and box.row_index is not None:
                row_boxes.setdefault(box.row_index, []).append(box)
        for row_index, row_detections in sorted(row_boxes.items()):
            ordered = sorted(row_detections, key=lambda item: (item.box_px.x, item.det_id))
            counts_by_row.setdefault(row_index, []).append({"seq": seq, "count": len(ordered)})
            tracks = tracks_by_row.setdefault(row_index, [])
            for box in ordered:
                choices = [
                    track
                    for track in tracks
                    if track.detections[-1][0].seq != seq
                    and frame.t_ms - track.detections[-1][0].t_ms <= max_gap_ms
                    and _x_overlap(box.box_px, track.detections[-1][1].box_px) >= min_x_overlap
                ]
                if choices:
                    selected = min(
                        choices,
                        key=lambda track: (
                            abs(_center_x(box) - _center_x(track.detections[-1][1])),
                            track.detections[0][0].seq,
                            track.detections[0][1].det_id,
                        ),
                    )
                    selected.detections.append((frame, box))
                else:
                    tracks.append(_Track(row_index, [(frame, box)]))

    review: list[dict[str, str]] = []
    rows = []
    books = []
    for row_index in sorted(set(tracks_by_row) | set(counts_by_row)):
        candidates = counts_by_row.get(row_index, [])
        counts = [candidate["count"] for candidate in candidates]
        if (
            counts
            and max(counts) > 0
            and (max(counts) - min(counts)) / max(counts) > disagreement_pct
        ):
            review.append({"ref_id": f"A-{row_index}", "code": "count_disagreement_row"})
        tracks = sorted(
            tracks_by_row.get(row_index, []),
            key=lambda track: (_track_x(track), _track_id(track)),
        )
        row_best_seq = _best_row_frame(tracks)
        row_best_frame = frame_by_seq.get(row_best_seq) if row_best_seq is not None else None
        row_bbox = _row_bbox(tracks, row_best_seq, row_best_frame)
        rows.append(
            {
                "row": row_index,
                "z_min": _row_min_y(tracks),
                "z_max": _row_max_y(tracks),
                "candidate_counts": candidates,
                "count": len(tracks),
                "best_frame_seq": _best_row_frame(tracks),
            }
        )
        for position, track in enumerate(tracks, start=1):
            best_frame, best_detection = max(
                track.detections,
                key=lambda pair: (
                    bool(pair[1].ocr_lines),
                    pair[0].blur if pair[0].blur is not None else -1,
                    -pair[0].seq,
                ),
            )
            books.append(
                {
                    "book_id": f"b_{len(books) + 1:04d}",
                    "unit": "A",
                    "row": row_index,
                    "position": position,
                    "member_dets": sorted({box.det_id for _, box in track.detections}),
                    "best_view": {
                        "seq": best_frame.seq,
                        "frame_ref": best_frame.path,
                        "bbox": best_detection.box_px.model_dump(),
                        "unit_bbox": (
                            row_bbox.model_dump()
                            if row_bbox is not None and best_frame.seq == row_best_seq
                            else BBox(x=0, y=0, w=best_frame.w, h=best_frame.h).model_dump()
                        ),
                        "ocr_lines": best_detection.ocr_lines,
                        "candidate_views": [
                            {
                                "seq": frame.seq,
                                "t_ms": frame.t_ms,
                                "frame_ref": frame.path,
                                "bbox": box.box_px.model_dump(),
                            }
                            for frame, box in track.detections
                        ],
                    },
                    "count_method": "ocr_row_position_dedup",
                }
            )
    return {"units": [{"unit": "A", "rows": rows}], "books": books, "review_queue": review}


def _x_overlap(first: BBox, second: BBox) -> float:
    overlap = max(0, min(first.x + first.w, second.x + second.w) - max(first.x, second.x))
    return overlap / max(1, min(first.w, second.w))


def _center_x(detection: Detection) -> float:
    return detection.box_px.x + detection.box_px.w / 2


def _track_x(track: _Track) -> float:
    best = max(track.detections, key=lambda pair: (pair[0].blur or -1, -pair[0].seq))
    return _center_x(best[1])


def _track_id(track: _Track) -> str:
    return min(box.det_id for _, box in track.detections)


def _row_min_y(tracks: list[_Track]) -> float:
    values = [box.box_px.y / frame.h for track in tracks for frame, box in track.detections]
    return min(values, default=0.0)


def _row_max_y(tracks: list[_Track]) -> float:
    values = [
        (box.box_px.y + box.box_px.h) / frame.h
        for track in tracks
        for frame, box in track.detections
    ]
    return max(values, default=0.0)


def _best_row_frame(tracks: list[_Track]) -> int | None:
    candidates = [pair for track in tracks for pair in track.detections]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: (pair[0].blur or -1, -pair[0].seq))[0].seq


def _row_bbox(tracks: list[_Track], seq: int | None, frame: FrameRecord | None) -> BBox | None:
    if seq is None or frame is None:
        return None
    boxes = [
        box.box_px
        for track in tracks
        for candidate, box in track.detections
        if candidate.seq == seq
    ]
    if not boxes:
        return None
    x0, y0 = min(box.x for box in boxes), min(box.y for box in boxes)
    x1 = max(box.x + box.w for box in boxes)
    y1 = max(box.y + box.h for box in boxes)
    return BBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
