from __future__ import annotations

import pytest
from app.prompts.loader import load_prompt
from app.settings import YamlSettings
from app.vision.bakeoff import _detect_with_retry, _map_spines
from app.vision.schema import FrameVisionObject, FrameVisionResponse


class TemporaryServerError(Exception):
    status_code = 503


def test_two_pass_prompts_are_registered_and_specific() -> None:
    assert "horizontal book rows" in load_prompt("shelf_rows")
    assert "individual visible book spines" in load_prompt("spine_boxes")


def test_vision_detection_default_matches_bakeoff_winner() -> None:
    assert YamlSettings().vision.detection_method == "full_frame"
    assert YamlSettings().vision.detection_model == "gemini-3.5-flash-lite"
    assert not YamlSettings().vision.detection_model_fallbacks
    assert YamlSettings().detection.max_keyframes == 6
    assert YamlSettings().transcribe.backend == "local_ocr"


class FlakyDetector:
    def __init__(self) -> None:
        self.calls = 0

    async def detect_with_prompt(self, image_bytes: bytes, prompt: str, model: str):
        del image_bytes, prompt, model
        self.calls += 1
        if self.calls < 4:
            raise TemporaryServerError("service unavailable")
        return FrameVisionResponse(objects=[])


@pytest.mark.asyncio
async def test_gemini_38_retries_500_or_503_four_attempts() -> None:
    detector = FlakyDetector()
    delays = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    result = await _detect_with_retry(
        detector, b"image", "prompt", "gemini-3.8-flash", record_delay
    )

    assert result.objects == []
    assert detector.calls == 4
    assert delays == [0.5, 1.5, 3.0]


def test_two_pass_spine_box_maps_crop_coordinates_to_full_frame() -> None:
    box = FrameVisionObject(cls="book_spine", box_2d=[0, 0, 1000, 1000])

    mapped = _map_spines([box], (100, 20, 500, 220), width=1000, height=500)

    assert mapped[0].box_2d == [40, 100, 440, 500]


def test_two_pass_mapping_drops_non_spine_boxes() -> None:
    box = FrameVisionObject(cls="item", box_2d=[100, 100, 900, 900])

    assert _map_spines([box], (0, 0, 100, 100), width=100, height=100) == []
