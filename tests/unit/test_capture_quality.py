from __future__ import annotations

import cv2
import numpy as np
from app.capture.quality import score_frame
from app.settings import Settings


def _checkerboard(low: int = 80, high: int = 220) -> np.ndarray:
    rows, columns = np.indices((960, 960))
    grid = ((rows // 24) + (columns // 24)) % 2
    gray = np.where(grid, high, low).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def test_sharp_checkerboard_scores_sharper_than_gaussian_blur() -> None:
    settings = Settings(_env_file=None).config.capture
    sharp = _checkerboard()
    blurred = cv2.GaussianBlur(sharp, (31, 31), 0)

    sharp_score = score_frame(sharp, settings)
    blurred_score = score_frame(blurred, settings)

    assert sharp_score.blur > blurred_score.blur
    assert blurred_score.verdict == "blurry"


def test_white_patch_triggers_glare_after_blur_check() -> None:
    settings = Settings(_env_file=None).config.capture
    image = _checkerboard()
    image[330:630, 330:630] = 255

    scores = score_frame(image, settings)

    assert scores.glare > settings.glare_max_frac
    assert scores.verdict == "glare"


def test_bright_exposure_and_fast_priority_are_reported() -> None:
    settings = Settings(_env_file=None).config.capture
    bright = score_frame(_checkerboard(211, 250), settings)
    fast = score_frame(_checkerboard(0, 20), settings, gyro_dps=61, fast_sustained=True)

    assert bright.exposure > settings.bright_mean
    assert bright.verdict == "bright"
    assert fast.verdict == "fast"


def test_low_light_blur_is_distinct_from_slow_capture_blur() -> None:
    settings = Settings(_env_file=None).config.capture
    dim_frame = np.full((240, 320, 3), 80, dtype=np.uint8)

    low_light = score_frame(dim_frame, settings, gyro_dps=10)
    no_motion_data = score_frame(dim_frame, settings)
    fast = score_frame(dim_frame, settings, gyro_dps=40, fast_sustained=True)

    assert low_light.blur < settings.blur_min
    assert low_light.exposure < settings.low_light_exposure_max
    assert low_light.verdict == "low_light_blur"
    assert no_motion_data.verdict == "blurry"
    assert fast.verdict == "fast"
