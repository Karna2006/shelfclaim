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
