from __future__ import annotations

import cv2
import numpy as np
import pytest
from app.settings import Settings, YamlSettings
from app.vision.detect_frame import detect_frame
from app.vision.schema import FrameVisionObject, FrameVisionResponse
from google.genai.errors import APIError


class FakeVision:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def detect_still(self, image_bytes: bytes, model: str) -> FrameVisionResponse:
        assert image_bytes.startswith(b"\xff\xd8")
        self.calls.append(model)
        if len(self.calls) < 3:
            raise APIError(503, {"status": "UNAVAILABLE", "message": "fixture outage"})
        return FrameVisionResponse(
            objects=[
                FrameVisionObject(cls="book_spine", box_2d=[100, 200, 900, 300]),
                FrameVisionObject(cls="shelf_unit", box_2d=[50, 50, 950, 950]),
            ]
        )


@pytest.mark.asyncio
async def test_detect_frame_retries_503_then_falls_back_and_draws_boxes(tmp_path) -> None:
    image_path = tmp_path / "frame.jpg"
    output_path = tmp_path / "annotated.png"
    assert cv2.imwrite(str(image_path), np.zeros((100, 120, 3), dtype=np.uint8))
    detector = FakeVision()
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    result = await detect_frame(
        image_path,
        output_path,
        Settings(config=YamlSettings(), _env_file=None),
        detector=detector,
        sleep=fake_sleep,
    )

    assert detector.calls == [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]
    assert delays == [0.5]
    assert result.model == "gemini-3.1-flash-lite"
    assert result.counts == {"book_spine": 1, "shelf_unit": 1}
    assert result.latency_ms >= 0
    assert output_path.is_file()
    annotated = cv2.imread(str(output_path))
    assert annotated is not None and np.any(annotated)
