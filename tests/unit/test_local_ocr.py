from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from app.vision.local_ocr import LocalOcrTranscriber
from app.vision.transcription import CropInput


class ShapeConfidenceEngine:
    def __init__(self) -> None:
        self.shapes: list[tuple[int, int]] = []

    def __call__(self, image: np.ndarray) -> SimpleNamespace:
        height, width = image.shape[:2]
        self.shapes.append((height, width))
        score = 0.9 if width > height else 0.7
        return SimpleNamespace(txts=("VISIBLE TITLE", "weak line"), scores=(score, 0.49))


def _crop(angle_deg: float) -> CropInput:
    image = np.full((120, 40, 3), 127, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return CropInput("b_0001_local", encoded.tobytes(), angle_deg)


@pytest.mark.asyncio
async def test_local_ocr_keeps_high_confidence_lines_and_best_rotation() -> None:
    engine = ShapeConfidenceEngine()
    transcriber = LocalOcrTranscriber(engine=engine)

    response = await transcriber.transcribe([_crop(90)])

    item = response.results[0]
    assert item.orientation == "rotate_90deg"
    assert [line.text for line in item.lines] == ["VISIBLE TITLE"]
    assert item.legibility == pytest.approx(0.9)
    assert len(engine.shapes) == 3


@pytest.mark.asyncio
async def test_flat_books_try_four_rotations_including_180() -> None:
    engine = ShapeConfidenceEngine()
    transcriber = LocalOcrTranscriber(engine=engine)

    await transcriber.transcribe([CropInput("flat_local", _crop(0).image_bytes, 180)])

    assert len(engine.shapes) == 4


@pytest.mark.asyncio
async def test_frame_ocr_maps_rotated_boxes_back_and_deduplicates() -> None:
    class FrameEngine:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, image: np.ndarray) -> SimpleNamespace:
            del image
            boxes = (
                [[[60, 10], [80, 10], [80, 30], [60, 30]]],
                [[[40, 50], [60, 50], [60, 70], [40, 70]]],
                [[[10, 40], [30, 40], [30, 60], [10, 60]]],
            )[self.calls]
            confidence = (0.8, 0.9, 0.75)[self.calls]
            self.calls += 1
            return SimpleNamespace(
                boxes=np.asarray(boxes), txts=("FRAME TITLE",), scores=(confidence,)
            )

    engine = FrameEngine()
    transcriber = LocalOcrTranscriber(engine=engine)

    lines = await transcriber.transcribe_frame(
        np.full((120, 80, 3), 100, dtype=np.uint8), include_upright=True
    )

    assert engine.calls == 3
    assert len(lines) == 1
    assert lines[0].text == "FRAME TITLE"
    assert lines[0].confidence == pytest.approx(0.9)
    assert (lines[0].x, lines[0].y, lines[0].w, lines[0].h) == pytest.approx((10, 40, 20, 20))
