"""Blur detected faces before evidence frames are written.

Input is a decoded BGR image; output is the redacted image and face count.
Uses OpenCV's bundled Haar cascade so capture needs no downloaded model.
"""

from __future__ import annotations

import cv2
import numpy as np


def blur_faces(frame: np.ndarray) -> tuple[np.ndarray, int]:
    """Return a copy with each Haar-detected face blurred and counted."""
    if frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
        raise ValueError("frame must be a non-empty BGR image")

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    classifier = cv2.CascadeClassifier(cascade_path)
    if classifier.empty():
        raise RuntimeError("OpenCV's bundled frontal-face cascade could not be loaded")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = classifier.detectMultiScale(gray)
    output = frame.copy()
    for x, y, width, height in faces:
        roi = output[y : y + height, x : x + width]
        # Deriving an odd kernel from the face bounds keeps the blur strong at either resolution.
        kernel = max(3, min(width, height) // 2)
        kernel += kernel % 2 == 0
        output[y : y + height, x : x + width] = cv2.GaussianBlur(roi, (kernel, kernel), 0)
    return output, len(faces)
