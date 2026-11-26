from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from app.packet.models import BBox
from app.pipeline.artifacts import Detection, DetectionsDoc, FrameRecord
from app.pipeline.orchestrator import run_pipeline
from app.pipeline.stages.s01_detect import run_detection_stage
from app.pipeline.stages.s03_books import build_book_clusters
from app.pipeline.stages.s04_measure import measure_spine_bbox
from app.settings import Settings, YamlSettings
from app.vision.keyframes import select_detection_keyframes
from app.vision.nms import suppress_frame_duplicates
from app.vision.schema import VisionObject, VisionResponse


def _box(det_id: str, x: int, width: int = 10) -> Detection:
    return Detection(det_id=det_id, cls="book_spine", box_px=BBox(x=x, y=10, w=width, h=50))


def test_nms_merges_duplicate_and_flags_borderline_pair() -> None:
    settings = YamlSettings().dedup
    first, duplicate, borderline = _box("a", 10), _box("b", 11), _box("c", 13)

    result = suppress_frame_duplicates([first, duplicate, borderline], settings)

    assert [item.det_id for item in result] == ["a", "c"]
    assert result[0].merged_from == ["b"]
    assert "possible_duplicate_box" in result[1].flags


class FakeVision:
    def __init__(self) -> None:
        self.calls = 0

    async def detect(self, image_bytes: bytes, model: str) -> VisionResponse:
        self.calls += 1
        assert image_bytes.startswith(b"\xff\xd8")
        assert model == "gemini-3.5-flash-lite"
        return VisionResponse(
            objects=[VisionObject(cls="book_spine", box_2d=(100, 200, 900, 300), angle_deg=90)]
        )


def _make_sweep(path, count: int = 1) -> None:
    (path / "frames").mkdir(parents=True)
    records = []
    for seq in range(count):
        image = np.random.default_rng(seq).integers(0, 255, (120, 100, 3), dtype=np.uint8)
        file = path / f"frames/{seq}.jpg"
        assert cv2.imwrite(str(file), image)
        records.append(
            FrameRecord(
                seq=seq,
                t_ms=seq * 1500,
                path=f"frames/{seq}.jpg",
                w=100,
                h=120,
                blur=400 - seq,
                qc_verdict="ok",
            )
        )
    (path / "frames.jsonl").write_text("".join(row.model_dump_json() + "\n" for row in records))


def test_keyframes_respect_interval_and_cap(tmp_path) -> None:
    _make_sweep(tmp_path, count=6)

    rows = select_detection_keyframes(tmp_path, YamlSettings().keyframes, max_frames=2)

    assert len(rows) <= 2
    assert all(right.t_ms - left.t_ms >= 1500 for left, right in zip(rows, rows[1:], strict=False))


@pytest.mark.asyncio
async def test_detection_stage_converts_normalized_boxes_to_pixels(tmp_path) -> None:
    _make_sweep(tmp_path)
    fake = FakeVision()

    output = await run_detection_stage(
        tmp_path, Settings(config=YamlSettings(), _env_file=None), fake
    )

    doc = json.loads(output.read_text())
    box = doc["frames"]["0"][0]["box_px"]
    assert box == {"x": 20, "y": 12, "w": 10, "h": 96, "angle_deg": 90.0}
    assert fake.calls == 1


def test_best_frame_row_count_and_candidate_disagreement() -> None:
    frames = [
        FrameRecord(seq=0, t_ms=0, path="frames/0.jpg", w=100, h=120, blur=500),
        FrameRecord(seq=1, t_ms=1500, path="frames/1.jpg", w=100, h=120, blur=400),
    ]
    per_frame = {}
    for seq, spine_count in ((0, 2), (1, 1)):
        boxes = [
            Detection(det_id=f"u{seq}", cls="shelf_unit", box_px=BBox(x=0, y=0, w=100, h=120)),
            Detection(det_id=f"t{seq}", cls="shelf_board", box_px=BBox(x=0, y=10, w=100, h=5)),
            Detection(det_id=f"b{seq}", cls="shelf_board", box_px=BBox(x=0, y=100, w=100, h=5)),
        ]
        boxes.extend(
            Detection(
                det_id=f"s{seq}-{index}",
                cls="book_spine",
                box_px=BBox(x=10 + index * 20, y=20, w=10, h=50),
            )
            for index in range(spine_count)
        )
        per_frame[seq] = boxes

    result = build_book_clusters(frames, DetectionsDoc(frames=per_frame))

    assert result["units"][0]["rows"][0]["count"] == 2
    assert result["units"][0]["rows"][0]["best_frame_seq"] == 0
    assert result["units"][0]["rows"][0]["candidate_counts"] == [
        {"seq": 0, "count": 2},
        {"seq": 1, "count": 1},
    ]
    assert result["review_queue"][0]["code"] == "count_disagreement_row"


def test_marker_homography_measures_synthetic_spine() -> None:
    dimensions = measure_spine_bbox(
        BBox(x=120, y=110, w=20, h=100),
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        100,
    )

    assert dimensions == (10.0, 2.0)


@pytest.mark.asyncio
async def test_orchestrator_records_geometry_off(tmp_path) -> None:
    class UnusedVision:
        async def detect(self, image_bytes: bytes, model: str) -> VisionResponse:
            raise AssertionError("empty sweep must not call the vision model")

    settings = Settings(config=YamlSettings(), geometry_backend="modal", _env_file=None)
    output = await run_pipeline(tmp_path, settings, until="s02", clients={"vision": UnusedVision()})

    geometry = json.loads((tmp_path / "s02_geometry.json").read_text())
    assert output.name == "s02_geometry.json"
    assert geometry["backend"] == "off"
    assert geometry["status"] == "skipped"
