"""Transcribe saved spine crops with CPU RapidOCR.

Input: JPEG crop bytes and box orientation. Output: best-rotation OCR lines and
mean character confidence; implements local, quota-independent Phase 6 reading.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import cv2
import numpy as np
from app.vision.schema import SpineLine, SpineTranscription, SpineTranscriptionResponse
from app.vision.transcription import CropInput
from rapidocr import RapidOCR


class OcrEngine(Protocol):
    def __call__(self, image: np.ndarray) -> Any: ...


class LocalOcrTranscriber:
    """Reuse one CPU OCR engine and select the rotation with clearest text."""

    def __init__(
        self,
        confidence_min: float = 0.5,
        *,
        engine: OcrEngine | None = None,
    ) -> None:
        self._confidence_min = confidence_min
        self._engine = engine or RapidOCR()

    async def transcribe(self, crops: list[CropInput]) -> SpineTranscriptionResponse:
        """Run synchronous CPU inference off the event loop."""
        return await asyncio.to_thread(self._transcribe_sync, crops)

    def _transcribe_sync(self, crops: list[CropInput]) -> SpineTranscriptionResponse:
        results = []
        for crop in crops:
            image = cv2.imdecode(np.frombuffer(crop.image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                results.append(SpineTranscription(crop_id=crop.crop_id))
                continue
            best = self._best_rotation(image, crop.angle_deg)
            results.append(
                SpineTranscription(
                    crop_id=crop.crop_id,
                    readable=bool(best["lines"]),
                    orientation=f"rotate_{best['angle']}deg",
                    lines=best["lines"],
                    legibility=best["confidence"],
                )
            )
        return SpineTranscriptionResponse(results=results)

    def _best_rotation(self, image: np.ndarray, angle_deg: float) -> dict[str, Any]:
        flat = _is_flat(angle_deg)
        angles = (0, 90, 270, 180) if flat else (0, 90, 270)
        best: dict[str, Any] = {"angle": 0, "lines": [], "confidence": 0.0}
        for angle in angles:
            rotated = _rotate(image, angle)
            lines, confidence = self._read_lines(rotated)
            if confidence > best["confidence"]:
                best = {"angle": angle, "lines": lines, "confidence": confidence}
        return best

    def _read_lines(self, image: np.ndarray) -> tuple[list[SpineLine], float]:
        result = self._engine(image)
        if result is None:
            return [], 0.0
        txts = getattr(result, "txts", ()) or ()
        scores = getattr(result, "scores", ()) or ()
        lines = []
        confidences = []
        for text, score in zip(txts, scores, strict=False):
            cleaned = str(text).strip()
            confidence = max(0.0, min(1.0, float(score)))
            if cleaned and confidence >= self._confidence_min:
                lines.append(SpineLine(text=cleaned, kind_guess="other"))
                confidences.append(confidence)
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return lines, mean_confidence


def _is_flat(angle_deg: float) -> bool:
    angle = angle_deg % 180
    return min(angle, 180 - angle) < 45


def _rotate(image: np.ndarray, angle: int) -> np.ndarray:
    rotation = {
        0: None,
        90: cv2.ROTATE_90_CLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE,
    }[angle]
    return image.copy() if rotation is None else cv2.rotate(image, rotation)
