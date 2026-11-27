from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from app.pipeline.artifacts import FrameRecord
from app.pipeline.context import StageContext
from app.pipeline.stages.s01_detect import run as run_detection
from app.settings import DetectionSettings, Settings, YamlSettings
from app.telemetry.ledger import Ledger
from app.vision.local_ocr import FrameOcrLine
from app.vision.ocr_detection import cluster_ocr_lines


def test_ocr_text_lines_cluster_by_row_then_horizontal_spine() -> None:
    lines = [
        _line("THE", x=20, y=100, w=12, h=160, ocr_height=10),
        _line("TITLE", x=22, y=145, w=12, h=145, ocr_height=10),
        _line("SECOND", x=102, y=105, w=12, h=155, ocr_height=10),
        _line("BOOK", x=101, y=150, w=12, h=145, ocr_height=10),
        _line("LOW CONFIDENCE", x=200, y=100, w=12, h=160, confidence=0.2),
        _line("SCREEN TEXT", x=200, y=170, w=18, h=22, ocr_height=10),
        _line("FLAT BOOK", x=180, y=410, w=100, h=20, rotation=0, ocr_height=20),
    ]

    clusters = cluster_ocr_lines(lines, 320, 600)

    assert [(cluster.row_index, [line.text for line in cluster.lines]) for cluster in clusters] == [
        (1, ["THE", "TITLE"]),
        (1, ["SECOND", "BOOK"]),
        (2, ["FLAT BOOK"]),
    ]
    assert clusters[0].box.x == 20
    assert clusters[0].box.w == 14
    assert clusters[0].box.angle_deg == 90


def test_ocr_flat_text_without_spine_shaped_context_is_not_a_book() -> None:
    clusters = cluster_ocr_lines(
        [_line("PROJECTS AND SEARCH", x=20, y=100, w=200, h=20, rotation=0)],
        320,
        600,
    )

    assert clusters == []


def test_ocr_splits_transitive_x_clusters_that_are_too_wide_for_one_spine() -> None:
    lines = [
        _line(f"LINE {index}", x=10 + index * 5, y=0, w=4, h=100, ocr_height=10)
        for index in range(11)
    ]

    clusters = cluster_ocr_lines(lines, 300, 100)

    assert len(clusters) == 2
    assert max(cluster.box.w for cluster in clusters) <= 55


@pytest.mark.asyncio
async def test_gemini_assist_failure_does_not_block_ocr_detections(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    image_path = frames_dir / "frame.jpg"
    assert cv2.imwrite(str(image_path), np.zeros((100, 120, 3), dtype=np.uint8))
    record = FrameRecord(
        seq=1,
        t_ms=1000,
        path="frames/frame.jpg",
        w=120,
        h=100,
        blur=300,
        qc_verdict="ok",
    )
    (tmp_path / "frames.jsonl").write_text(record.model_dump_json() + "\n", encoding="utf-8")

    class FakeOcr:
        async def transcribe_frame(self, image: np.ndarray, *, include_upright: bool = False):
            assert image.shape[:2] == (100, 120)
            assert include_upright
            return [_line("VISIBLE TITLE", x=20, y=10, w=12, h=80, ocr_height=10)]

    class FailedVision:
        async def detect(self, image_bytes: bytes, model: str):
            del image_bytes, model
            raise RuntimeError("fixture model failure")

    config = YamlSettings(
        detection=DetectionSettings(backend="ocr_spines", assist="gemini", max_keyframes=1)
    )
    context = StageContext(
        tmp_path,
        Settings(config=config, _env_file=None),
        Ledger(),
        {"local_ocr": FakeOcr(), "vision": FailedVision()},
    )

    output = await run_detection(context, frame_seqs=(1,))
    document = json.loads(output.read_text(encoding="utf-8"))

    assert document["backend"] == "ocr_spines"
    assert len(document["frames"]["1"]) == 1
    assert document["keyframe_stats"][0]["spine_count"] == 1
    assert "All vision models failed" in document["keyframe_stats"][0]["errors"][0]


def _line(
    text: str,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    confidence: float = 0.9,
    rotation: int = 90,
    ocr_height: float = 10,
) -> FrameOcrLine:
    return FrameOcrLine(
        text,
        confidence,
        x,
        y,
        w,
        h,
        rotation=rotation,
        ocr_height=ocr_height,
    )
