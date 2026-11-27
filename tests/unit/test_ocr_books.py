from __future__ import annotations

from app.packet.models import BBox
from app.pipeline.artifacts import Detection, DetectionsDoc, FrameRecord
from app.vision.ocr_books import build_ocr_book_clusters


def test_ocr_book_tracks_keep_candidate_counts_and_choose_sharpest_view() -> None:
    frames = [
        _frame(1, 1000, 250),
        _frame(2, 2000, 380),
    ]
    detections = DetectionsDoc(
        backend="ocr_spines",
        frames={
            1: [_detection("one-a", 100), _detection("one-b", 180)],
            2: [_detection("two-a", 105), _detection("two-b", 185)],
        },
    )

    result = build_ocr_book_clusters(
        frames,
        detections,
        max_gap_ms=3000,
        min_x_overlap=0.5,
        disagreement_pct=0.1,
    )

    assert len(result["books"]) == 2
    assert [book["position"] for book in result["books"]] == [1, 2]
    assert {book["best_view"]["seq"] for book in result["books"]} == {2}
    assert [book["count_method"] for book in result["books"]] == [
        "ocr_row_position_dedup",
        "ocr_row_position_dedup",
    ]
    assert result["units"][0]["rows"][0]["candidate_counts"] == [
        {"seq": 1, "count": 2},
        {"seq": 2, "count": 2},
    ]
    assert not result["review_queue"]


def test_ocr_book_tracks_do_not_merge_boxes_when_time_gap_is_too_large() -> None:
    result = build_ocr_book_clusters(
        [_frame(1, 0, 300), _frame(2, 9000, 300)],
        DetectionsDoc(
            backend="ocr_spines",
            frames={1: [_detection("one", 100)], 2: [_detection("two", 100)]},
        ),
        max_gap_ms=5000,
        min_x_overlap=0.5,
        disagreement_pct=0.1,
    )

    assert len(result["books"]) == 2


def _frame(seq: int, t_ms: int, blur: float) -> FrameRecord:
    return FrameRecord(
        seq=seq,
        t_ms=t_ms,
        path=f"frames/{seq}.jpg",
        w=400,
        h=300,
        blur=blur,
        qc_verdict="ok",
    )


def _detection(det_id: str, x: int) -> Detection:
    return Detection(
        det_id=det_id,
        cls="book_spine",
        box_px=BBox(x=x, y=50, w=40, h=180),
        row_index=1,
        ocr_lines=[{"text": det_id, "confidence": 0.9}],
    )
