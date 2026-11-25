"""Measure deterministic per-frame capture quality.

Input is a decoded BGR image and optional gyro rate; output is a typed metric
record following `docs/04_ARCHITECTURE.md` §4.1 and `config/settings.yaml`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from app.settings import CaptureSettings

Verdict = Literal["ok", "blurry", "low_light_blur", "glare", "dark", "bright", "fast"]


@dataclass(frozen=True)
class QualityScores:
    blur: float | None
    glare: float | None
    exposure: float | None
    speed_dps: float | None
    verdict: Verdict


def score_frame(
    frame: np.ndarray,
    settings: CaptureSettings,
    gyro_dps: float | None = None,
    fast_sustained: bool = False,
) -> QualityScores:
    """Score an image using documented image regions and configured thresholds."""
    if frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
        raise ValueError("frame must be a non-empty BGR image")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Fixed analysis width keeps blur scores comparable across camera resolutions.
    target_width = 960
    blur_gray = cv2.resize(
        gray,
        (target_width, max(1, round(gray.shape[0] * target_width / gray.shape[1]))),
    )
    blur = float(cv2.Laplacian(blur_gray, cv2.CV_64F).var())

    height, width = frame.shape[:2]
    # A 10% inset on each edge leaves the architecture's central 80% for glare scoring.
    x0, x1 = round(width * 0.1), round(width * 0.9)
    y0, y1 = round(height * 0.1), round(height * 0.9)
    central = frame[y0:y1, x0:x1]
    value = cv2.cvtColor(central, cv2.COLOR_BGR2HSV)[:, :, 2]
    glare = float(np.count_nonzero(value > 250) / value.size)
    exposure = float(cv2.mean(gray)[0])

    verdict = classify_verdict(
        blur, glare, exposure, gyro_dps, settings, fast_sustained=fast_sustained
    )

    return QualityScores(blur, glare, exposure, gyro_dps, verdict)


def classify_verdict(
    blur: float | None,
    glare: float | None,
    exposure: float | None,
    gyro_dps: float | None,
    settings: CaptureSettings,
    *,
    fast_sustained: bool = False,
) -> Verdict:
    """Assign one QC reason, prioritizing sustained motion and low-light blur."""
    if fast_sustained:
        return "fast"
    is_blurry = blur is not None and blur < settings.blur_min
    if (
        is_blurry
        and gyro_dps is not None
        and gyro_dps < settings.speed_max_dps
        and exposure is not None
        and exposure < settings.low_light_exposure_max
    ):
        return "low_light_blur"
    if is_blurry:
        return "blurry"
    if glare is not None and glare > settings.glare_max_frac:
        return "glare"
    if exposure is not None and exposure < settings.dark_mean:
        return "dark"
    if exposure is not None and exposure > settings.bright_mean:
        return "bright"
    return "ok"
