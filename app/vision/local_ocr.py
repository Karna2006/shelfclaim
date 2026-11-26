"""Transcribe saved spine crops with CPU RapidOCR.

Input: JPEG crop bytes and box orientation. Output: best-rotation OCR lines and
mean character confidence; implements local, quota-independent Phase 6 reading.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np
from app.vision.schema import SpineLine, SpineTranscription, SpineTranscriptionResponse
from app.vision.transcription import CropInput
from rapidocr import RapidOCR


@dataclass(frozen=True)
class FrameOcrLine:
    """A confident OCR line located in the unrotated source frame."""

    text: str
    confidence: float
    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


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

    async def transcribe_frame(
        self, image: np.ndarray, *, include_upright: bool = False
    ) -> list[FrameOcrLine]:
        """Detect and locate text on full-frame rotations in source coordinates."""
        return await asyncio.to_thread(self._transcribe_frame_sync, image, include_upright)

    def _transcribe_frame_sync(
        self, image: np.ndarray, include_upright: bool
    ) -> list[FrameOcrLine]:
        angles = (90, 270, 0) if include_upright else (90, 270)
        height, width = image.shape[:2]
        lines: list[FrameOcrLine] = []
        for angle in angles:
            rotated = _rotate(image, angle)
            result = self._engine(rotated)
            boxes = getattr(result, "boxes", None)
            txts = getattr(result, "txts", None)
            scores = getattr(result, "scores", None)
            if boxes is None or txts is None or scores is None:
                continue
            for box, text, score in zip(boxes, txts, scores, strict=False):
                cleaned = str(text).strip()
                confidence = max(0.0, min(1.0, float(score)))
                if not cleaned or confidence < self._confidence_min:
                    continue
                source_box = _box_to_source(box, angle, width, height)
                if source_box is None:
                    continue
                x0, y0, x1, y1 = source_box
                lines.append(FrameOcrLine(cleaned, confidence, x0, y0, x1 - x0, y1 - y0))
        return _deduplicate_frame_lines(lines)

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


def _box_to_source(
    box: Any, angle: int, width: int, height: int
) -> tuple[float, float, float, float] | None:
    points = np.asarray(box, dtype=np.float32).reshape(-1, 2)
    if points.size == 0:
        return None
    if angle == 90:
        mapped = np.column_stack((points[:, 1], height - points[:, 0]))
    elif angle == 270:
        mapped = np.column_stack((width - points[:, 1], points[:, 0]))
    else:
        mapped = points
    x0 = float(np.clip(mapped[:, 0].min(), 0, width))
    y0 = float(np.clip(mapped[:, 1].min(), 0, height))
    x1 = float(np.clip(mapped[:, 0].max(), 0, width))
    y1 = float(np.clip(mapped[:, 1].max(), 0, height))
    return None if x1 <= x0 or y1 <= y0 else (x0, y0, x1, y1)


def _deduplicate_frame_lines(lines: list[FrameOcrLine]) -> list[FrameOcrLine]:
    selected: list[FrameOcrLine] = []
    for line in lines:
        normalized = _normalize_ocr_text(line.text)
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(selected)
                if _normalize_ocr_text(existing.text) == normalized
                and _overlap_fraction(line, existing) >= 0.5
            ),
            None,
        )
        if duplicate_index is None:
            selected.append(line)
        elif line.confidence > selected[duplicate_index].confidence:
            selected[duplicate_index] = line
    return selected


def _overlap_fraction(first: FrameOcrLine, second: FrameOcrLine) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.w, second.x + second.w)
    bottom = min(first.y + first.h, second.y + second.h)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    smaller = min(first.w * first.h, second.w * second.h)
    return intersection / smaller if smaller > 0 else 0.0


def _normalize_ocr_text(text: str) -> str:
    return "".join(character.casefold() for character in text if character.isalnum())
