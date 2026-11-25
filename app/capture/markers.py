"""Detect scale-card markers in each captured frame.

Input is a decoded BGR image and app settings; output is marker IDs and pixel
corners matching `docs/05_DATA_SCHEMA.md` §2.
"""

from __future__ import annotations

import cv2
import numpy as np
from app.pipeline.artifacts import MarkerObservation
from app.settings import Settings


def detect_markers(frame: np.ndarray, settings: Settings) -> list[MarkerObservation]:
    """Detect configured ArUco markers and return their four image-space corners."""
    aruco = cv2.aruco
    dictionary_id = getattr(aruco, settings.marker_dict, None)
    if dictionary_id is None:
        raise ValueError(f"Unknown ArUco dictionary: {settings.marker_dict}")
    dictionary = aruco.getPredefinedDictionary(dictionary_id)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if hasattr(aruco, "ArucoDetector"):
        corners, ids, _ = aruco.ArucoDetector(dictionary).detectMarkers(gray)
    else:
        corners, ids, _ = aruco.detectMarkers(gray, dictionary)
    if ids is None:
        return []

    return [
        MarkerObservation(
            id=int(marker_id),
            corners=[(float(point[0]), float(point[1])) for point in marker_corners.reshape(4, 2)],
        )
        for marker_id, marker_corners in zip(ids.flatten(), corners, strict=True)
    ]
