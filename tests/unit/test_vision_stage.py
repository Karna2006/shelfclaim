from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from app.cli import _format_s03_count_rows, _print_detection_keyframe_stats, pick_frames
from app.live.rate_limit import ModelRateLimiter
from app.packet.models import BBox
from app.pipeline.artifacts import Detection, DetectionsDoc, FrameRecord
from app.pipeline.orchestrator import run_pipeline
from app.pipeline.stages.s01_detect import run_detection_stage
from app.pipeline.stages.s03_books import build_book_clusters
from app.pipeline.stages.s04_measure import measure_spine_bbox
from app.settings import LlmSettings, ModelRateLimitSettings, Settings, YamlSettings
from app.vision.keyframes import select_detection_keyframes
from app.vision.nms import suppress_frame_duplicates
from app.vision.schema import VisionObject, VisionResponse
from google.genai.errors import APIError


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


def test_keyframes_cover_segments_and_respect_budget(tmp_path) -> None:
    _make_sweep(tmp_path, count=45)

    rows = select_detection_keyframes(tmp_path, max_frames=2)
    capped_rows = select_detection_keyframes(tmp_path, max_frames=6)

    assert len(rows.frames) == 2
    assert [choice.segment for choice in rows.choices] == [0, 1]
    assert len(capped_rows.frames) == 6
    assert [choice.segment for choice in capped_rows.choices] == list(range(6))


def test_keyframes_choose_sharpest_ok_frame_and_flag_quality_fallback(tmp_path) -> None:
    _make_sweep(tmp_path, count=12)
    records = [
        FrameRecord.model_validate_json(line)
        for line in (tmp_path / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    adjusted = []
    for frame in records:
        seq = frame.seq
        verdict = "blurry" if seq in {1, 2, 3} else "ok"
        blur = float(seq * 100 + 100)
        adjusted.append(
            frame.model_copy(update={"t_ms": seq * 1000, "qc_verdict": verdict, "blur": blur})
        )
    (tmp_path / "frames.jsonl").write_text(
        "".join(frame.model_dump_json() + "\n" for frame in adjusted), encoding="utf-8"
    )

    selection = select_detection_keyframes(tmp_path, max_frames=6)

    assert [frame.seq for frame in selection.frames] == [0, 3, 5, 7, 9, 11]
    assert [choice.segment for choice in selection.review_choices] == [1]
    assert selection.review_choices[0].quality_fallback is True


@pytest.mark.asyncio
async def test_replay_keyframe_output_lists_selected_frames_and_paths(tmp_path, capsys) -> None:
    _make_sweep(tmp_path, count=12)

    limiter = ModelRateLimiter(
        LlmSettings(default_rate_limit=ModelRateLimitSettings(requests_per_minute=100))
    )
    await run_detection_stage(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        FakeVision(),
        limiter=limiter,
    )
    _print_detection_keyframe_stats(tmp_path)

    output = capsys.readouterr().out
    assert "Selected keyframes: segment | seq | QC | blur | fallback | frame" in output
    assert str(tmp_path / "frames/0.jpg") in output
    assert str(tmp_path / "frames/10.jpg") in output


def test_pick_frames_cli_reports_selected_frame_paths(tmp_path, capsys) -> None:
    _make_sweep(tmp_path, count=4)

    pick_frames(tmp_path, n=2)

    output = capsys.readouterr().out
    assert "rank | seq | blur" in output
    assert str(tmp_path / "frames/0.jpg") in output


@pytest.mark.asyncio
async def test_detection_stage_converts_normalized_boxes_to_pixels(tmp_path) -> None:
    _make_sweep(tmp_path)
    fake = FakeVision()

    output = await run_detection_stage(
        tmp_path,
        Settings(config=YamlSettings(), vision_model="gemini-3.8-flash", _env_file=None),
        fake,
    )

    doc = json.loads(output.read_text())
    box = doc["frames"]["0"][0]["box_px"]
    assert box == {"x": 20, "y": 12, "w": 10, "h": 96, "angle_deg": 90.0}
    stats = doc["keyframe_stats"][0]
    assert stats["seq"] == 0
    assert stats["model"] == "gemini-3.5-flash-lite"
    assert isinstance(stats["latency_ms"], int) and stats["latency_ms"] >= 0
    assert (stats["spine_count"], stats["shelf_board_count"], stats["item_count"]) == (1, 0, 0)
    assert fake.calls == 1
    assert doc["selected_keyframes"] == [
        {
            "seq": 0,
            "segment": 0,
            "qc_verdict": "ok",
            "blur": 400.0,
            "quality_fallback": False,
        }
    ]


@pytest.mark.asyncio
async def test_detection_stage_uses_explicit_reviewed_frame_sequences(tmp_path) -> None:
    _make_sweep(tmp_path, count=4)
    fake = FakeVision()

    output = await run_detection_stage(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        fake,
        frame_seqs=(3, 1),
    )

    document = DetectionsDoc.model_validate_json(output.read_text())
    assert [row.seq for row in document.keyframe_stats] == [3, 1]
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_detection_stage_rejects_repeated_explicit_frame_sequence(tmp_path) -> None:
    _make_sweep(tmp_path, count=2)

    with pytest.raises(ValueError, match="unique saved frame"):
        await run_detection_stage(
            tmp_path,
            Settings(config=YamlSettings(), _env_file=None),
            FakeVision(),
            frame_seqs=(0, 0),
        )


@pytest.mark.asyncio
async def test_detection_stage_retries_503_then_uses_next_model(tmp_path) -> None:
    _make_sweep(tmp_path)

    class BusyThenAvailable:
        def __init__(self) -> None:
            self.models: list[str] = []

        async def detect(self, image_bytes: bytes, model: str) -> VisionResponse:
            self.models.append(model)
            if len(self.models) <= 2:
                raise APIError(503, {"status": "UNAVAILABLE", "message": "fixture outage"})
            return VisionResponse(
                objects=[VisionObject(cls="book_spine", box_2d=[100, 200, 900, 300])]
            )

    detector = BusyThenAvailable()
    output = await run_detection_stage(
        tmp_path,
        Settings(
            config=YamlSettings(vision={"detection_model_fallbacks": True}),
            _env_file=None,
        ),
        detector,
    )
    document = json.loads(output.read_text(encoding="utf-8"))

    assert detector.models == [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]
    assert document["keyframe_stats"][0]["model"] == "gemini-3.1-flash-lite"


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


def test_s03_summary_reports_best_frame_and_candidate_range() -> None:
    result = {
        "units": [
            {
                "unit": "A",
                "rows": [
                    {
                        "row": 1,
                        "count": 2,
                        "best_frame_seq": 4,
                        "candidate_counts": [
                            {"seq": 0, "count": 3},
                            {"seq": 4, "count": 2},
                        ],
                    }
                ],
            }
        ]
    }

    lines = _format_s03_count_rows(result, {4: "frames/f_000004.jpg"})

    assert lines == ["A | 1 | 2 | 4 (frames/f_000004.jpg) | 2 | 3"]


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


@pytest.mark.asyncio
async def test_orchestrator_reuses_existing_s1_for_s03(tmp_path) -> None:
    class UnusedVision:
        async def detect(self, image_bytes: bytes, model: str) -> VisionResponse:
            raise AssertionError("existing S1 should be reused")

    _make_sweep(tmp_path)
    detections_path = tmp_path / "s01_detections.json"
    detections_path.write_text(DetectionsDoc().model_dump_json(), encoding="utf-8")
    settings = Settings(config=YamlSettings(), _env_file=None)

    output = await run_pipeline(
        tmp_path,
        settings,
        until="s03",
        clients={"vision": UnusedVision()},
    )

    assert output.name == "s03_books_raw.json"
    assert json.loads(output.read_text(encoding="utf-8"))["units"] == []
    assert detections_path.is_file()
