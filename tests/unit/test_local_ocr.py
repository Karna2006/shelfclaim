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
