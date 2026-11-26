"""Detect objects in one still image and save an annotated preview.

Input: a JPEG, model settings, and an output PNG path. Output: class counts,
the successful model and latency plus drawn detections. Implements CLI support.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from app.settings import Settings
from app.vision.client import GeminiVisionDetector
from app.vision.models import VISION_MODEL_FALLBACKS
from app.vision.schema import FrameVisionObject, FrameVisionResponse

MODEL_FALLBACK_CHAIN = VISION_MODEL_FALLBACKS
_RETRIES_ON_503 = 1
_RETRY_DELAY_S = 0.5


class AsyncSleep(Protocol):
    async def __call__(self, delay: float) -> None: ...


class FrameVisionDetector(Protocol):
    async def detect_still(self, image_bytes: bytes, model: str) -> FrameVisionResponse: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class FrameDetectionResult:
    model: str
    latency_ms: int
    counts: dict[str, int]
    output_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "counts_per_class": self.counts,
            "model_used": self.model,
            "latency_ms": self.latency_ms,
            "annotated_image": str(self.output_path),
        }


async def detect_frame(
    image_path: Path,
    output_path: Path,
    settings: Settings,
    *,
    detector: FrameVisionDetector | None = None,
    sleep: AsyncSleep = asyncio.sleep,
) -> FrameDetectionResult:
    """Run a single-image detection with one 503 retry before model fallback."""
    if image_path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("Input image must be a JPG")
    if output_path.suffix.lower() != ".png":
        raise ValueError("Output path must use the .png extension")
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read JPG image: {image_path}")

    owned_detector = detector is None
    vision = detector or GeminiVisionDetector(settings)
    started = time.perf_counter()
    try:
        response, model = await _detect_with_fallback(
            vision, image_path.read_bytes(), settings, sleep
        )
    finally:
        if owned_detector:
            await vision.close()  # type: ignore[attr-defined]
    latency_ms = round((time.perf_counter() - started) * 1000)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _draw_detections(image, response.objects)
    if not cv2.imwrite(str(output_path), image):
        raise OSError(f"Could not save annotated image: {output_path}")
    counts = dict(sorted(Counter(item.cls for item in response.objects).items()))
    return FrameDetectionResult(
        model=model,
        latency_ms=latency_ms,
        counts=counts,
        output_path=output_path,
    )


async def _detect_with_fallback(
    detector: FrameVisionDetector,
    image_bytes: bytes,
    settings: Settings,
    sleep: AsyncSleep,
) -> tuple[FrameVisionResponse, str]:
    failures: list[str] = []
    for model in MODEL_FALLBACK_CHAIN:
        for attempt in range(_RETRIES_ON_503 + 1):
            try:
                return await detector.detect_still(image_bytes, model), model
            except Exception as exc:
                if _status_code(exc) == 503 and attempt < _RETRIES_ON_503:
                    await sleep(_RETRY_DELAY_S)
                    continue
                status = _status_code(exc) or "no status"
                detail = _safe_error_detail(exc, settings)
                failures.append(
                    f"{model}: {type(exc).__name__} ({status})" + (f" - {detail}" if detail else "")
                )
                break
    raise RuntimeError("All vision models failed: " + "; ".join(failures))


def _status_code(error: Exception) -> int | None:
    for attribute in ("code", "status_code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    return None


def _safe_error_detail(error: Exception, settings: Settings) -> str:
    detail = getattr(error, "message", None)
    if not isinstance(detail, str):
        return ""
    if settings.google_api_key is not None:
        secret = settings.google_api_key.get_secret_value()
        if secret:
            detail = detail.replace(secret, "[redacted]")
    return detail[:240]


def _draw_detections(image: np.ndarray, detections: list[FrameVisionObject]) -> None:
    height, width = image.shape[:2]
    for detection in detections:
        box = _pixel_box(detection, width, height)
        if box is None:
            continue
        x, y, box_width, box_height = box
        rectangle = (
            (x + box_width / 2, y + box_height / 2),
            (box_width, box_height),
            detection.angle_deg,
        )
        points = cv2.boxPoints(rectangle).astype(np.int32)
        cv2.polylines(image, [points], True, (30, 220, 40), 2)
        cv2.putText(
            image,
            detection.cls,
            (x, max(18, y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (30, 220, 40),
            1,
            cv2.LINE_AA,
        )


def _pixel_box(
    detection: FrameVisionObject, width: int, height: int
) -> tuple[int, int, int, int] | None:
    ymin, xmin, ymax, xmax = detection.box_2d
    x0, x1 = sorted((max(0, min(1000, xmin)), max(0, min(1000, xmax))))
    y0, y1 = sorted((max(0, min(1000, ymin)), max(0, min(1000, ymax))))
    left, right = round(x0 * width / 1000), round(x1 * width / 1000)
    top, bottom = round(y0 * height / 1000), round(y1 * height / 1000)
    left, top = min(width - 1, left), min(height - 1, top)
    box_width = min(width - left, max(1, right - left))
    box_height = min(height - top, max(1, bottom - top))
    return left, top, box_width, box_height
