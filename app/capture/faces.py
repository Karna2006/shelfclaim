"""Detect and blur faces before evidence frames are written.

Input is a decoded BGR image and capture thresholds; output is the redacted image
and audited face boxes. Implements the privacy safeguard in `docs/02_PRD.md` §8.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from app.settings import CaptureSettings

FaceBox = tuple[int, int, int, int, float | None]
_MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"


def blur_faces(
    frame: np.ndarray,
    settings: CaptureSettings | None = None,
    model_path: Path | None = None,
) -> tuple[np.ndarray, list[FaceBox]]:
    """Redact YuNet detections, using strict Haar detection when the model is absent."""
    if frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
        raise ValueError("frame must be a non-empty BGR image")

    selected_settings = settings or CaptureSettings()
    selected_model = model_path or _default_model_path()
    if selected_model.is_file():
        boxes = _detect_yunet(frame, selected_model, selected_settings.face_score_threshold)
    else:
        boxes = _detect_haar(frame, selected_settings)
    return _blur_boxes(frame, boxes), boxes


def _default_model_path() -> Path:
    return Path(__file__).resolve().parents[2] / "models" / _MODEL_FILENAME


def _detect_yunet(frame: np.ndarray, model_path: Path, score_threshold: float) -> list[FaceBox]:
    height, width = frame.shape[:2]
    detector = cv2.FaceDetectorYN.create(
        str(model_path), "", (width, height), score_threshold, 0.3, 5000
    )
    _, detections = detector.detect(frame)
    if detections is None:
        return []
    boxes = [
        _bounded_box(row[0], row[1], row[2], row[3], width, height, float(row[14]))
        for row in detections
    ]
    return [box for box in boxes if box[2] > 0 and box[3] > 0]


def _detect_haar(frame: np.ndarray, settings: CaptureSettings) -> list[FaceBox]:
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    classifier = cv2.CascadeClassifier(cascade_path)
    if classifier.empty():
        raise RuntimeError("OpenCV's bundled frontal-face cascade could not be loaded")

    height, width = frame.shape[:2]
    short_side = min(height, width)
    min_face_side = max(1, math.ceil(short_side * settings.haar_min_size_fraction))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = classifier.detectMultiScale(
        gray,
        scaleFactor=settings.haar_scale_factor,
        minNeighbors=settings.haar_min_neighbors,
        minSize=(min_face_side, min_face_side),
    )
    return [
        _bounded_box(x, y, box_width, box_height, width, height, None)
        for x, y, box_width, box_height in faces
    ]


def _bounded_box(
    x: float,
    y: float,
    box_width: float,
    box_height: float,
    frame_width: int,
    frame_height: int,
    score: float | None,
) -> FaceBox:
    left = max(0, min(frame_width, round(x)))
    top = max(0, min(frame_height, round(y)))
    right = max(left, min(frame_width, round(x + box_width)))
    bottom = max(top, min(frame_height, round(y + box_height)))
    return left, top, right - left, bottom - top, score


def _blur_boxes(frame: np.ndarray, boxes: list[FaceBox]) -> np.ndarray:
    output = frame.copy()
    for x, y, width, height, _ in boxes:
        if width == 0 or height == 0:
            continue
        roi = output[y : y + height, x : x + width]
        kernel = max(3, min(width, height) // 2)
        kernel += kernel % 2 == 0
        output[y : y + height, x : x + width] = cv2.GaussianBlur(roi, (kernel, kernel), 0)
    return output
