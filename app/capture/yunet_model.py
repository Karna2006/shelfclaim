"""Download the pinned YuNet face detector used during capture.

Input is a local destination; output is the checksum-verified ONNX model.
The verified model file itself acts as the local cache for repeated setup runs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.net.http import fetch_bytes

MODEL_URL = (
    "https://huggingface.co/opencv/face_detection_yunet/resolve/"
    "3cc26e7f1014a5ee5d74a42acee58bafc9d0a310/"
    "face_detection_yunet_2023mar.onnx?download=true"
)
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_PATH = Path("models/face_detection_yunet_2023mar.onnx")


async def download_yunet_model(
    destination: Path = MODEL_PATH,
    cache_path: Path = Path("cache/http_cache.sqlite"),
) -> Path:
    """Download and atomically install YuNet only when its SHA-256 matches."""
    if destination.is_file() and _sha256(destination.read_bytes()) == MODEL_SHA256:
        return destination

    model_bytes = await fetch_bytes(MODEL_URL, cache_path)
    if _sha256(model_bytes) != MODEL_SHA256:
        raise ValueError("Downloaded YuNet model SHA-256 did not match the pinned value")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".tmp")
    temporary_path.write_bytes(model_bytes)
    temporary_path.replace(destination)
    return destination


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
