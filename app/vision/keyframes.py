"""Select sharp, novel images for paid vision calls.

Input: a saved sweep manifest and per-frame quality scores. Output: at most
one non-duplicate frame per configured interval, capped at 60 per sweep.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from app.capture.storage import list_frames
from app.pipeline.artifacts import FrameRecord
from app.settings import KeyframeSettings


def select_detection_keyframes(
    sweep_dir: Path,
    settings: KeyframeSettings,
    *,
    max_frames: int | None = None,
    interval_s: float | None = None,
) -> list[FrameRecord]:
    """Choose the sharpest frame in each interval and remove near-identical views."""
    records = list_frames(sweep_dir)
    if not records:
        return []
    max_frames = max_frames or settings.detection_max_frames
    interval_s = interval_s or settings.detection_interval_s
    origin_ms = records[0].t_ms
    buckets: dict[int, list[FrameRecord]] = {}
    for record in records:
        bucket = int((record.t_ms - origin_ms) // (interval_s * 1000))
        buckets.setdefault(bucket, []).append(record)
    candidates = [
        max(bucket, key=lambda row: (row.blur if row.blur is not None else -1, -row.seq))
        for bucket in buckets.values()
    ]
    candidates.sort(key=lambda row: row.t_ms)
    selected: list[FrameRecord] = []
    fingerprints: list[np.ndarray] = []
    for record in candidates:
        image = cv2.imread(str(sweep_dir / record.path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        fingerprint = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
        if any(
            float(np.mean(np.abs(fingerprint - prior))) / 255 < settings.min_novelty
            for prior in fingerprints
        ):
            continue
        selected.append(record)
        fingerprints.append(fingerprint)
        if len(selected) >= max_frames:
            break
    return selected
