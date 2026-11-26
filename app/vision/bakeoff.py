"""Compare whole-frame and spine-first shelf detection on saved frames.

Inputs: sweep frame IDs, vision settings, and an optional fake detector. Outputs:
annotated PNGs and per-method counts for the documented S1 box schema.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from app.capture.storage import list_frames
from app.prompts.loader import load_prompt
from app.settings import Settings
from app.vision.client import GeminiVisionDetector
from app.vision.schema import FrameVisionObject, FrameVisionResponse

_RETRY_DELAYS_S = (0.5, 1.5, 3.0)


class PromptDetector(Protocol):
    async def detect_with_prompt(
        self, image_bytes: bytes, prompt: str, model: str
    ) -> FrameVisionResponse: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class BakeoffResult:
    method: str
    seq: int
    model: str
    latency_ms: int
    counts: dict[str, int]
    output_path: Path
    error: str | None = None


async def run_detection_bakeoff(
    sweep: Path,
    frame_seqs: tuple[int, ...],
    settings: Settings,
    *,
    two_pass_model: str,
    include_single: bool = True,
    include_two_pass: bool = True,
    detector: PromptDetector | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[BakeoffResult]:
    """Run both single-pass models and the row-crop method on selected frames."""
    records = {record.seq: record for record in list_frames(sweep)}
    if not frame_seqs or any(seq not in records for seq in frame_seqs):
        raise ValueError("Every requested frame sequence must exist in the sweep")
    if not include_single and not include_two_pass:
        raise ValueError("At least one bake-off method must be enabled")
    owns_detector = detector is None
    vision = detector or GeminiVisionDetector(settings)
    output_dir = sweep / "detection_bakeoff"
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[BakeoffResult] = []
    try:
        for seq in frame_seqs:
            record = records[seq]
            image_path = sweep / record.path
            image_bytes = image_path.read_bytes()
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"Could not decode frame {image_path}")
            if include_single:
                for model in ("gemini-3.8-flash", "gemini-3.5-flash-lite"):
                    results.append(
                        await _run_single(vision, image, image_bytes, seq, model, output_dir, sleep)
                    )
            if include_two_pass:
                results.append(
                    await _run_two_pass(vision, image, image_bytes, seq, two_pass_model, output_dir)
                )
    finally:
        if owns_detector:
            await vision.close()
    return results


async def _run_single(
    detector: PromptDetector,
    image: np.ndarray,
    image_bytes: bytes,
    seq: int,
    model: str,
    output_dir: Path,
    sleep: Callable[[float], Awaitable[None]],
) -> BakeoffResult:
    method = model.replace("gemini-", "")
    started = time.perf_counter()
    response: FrameVisionResponse | None = None
    error = None
    try:
        response = await _detect_with_retry(
            detector,
            image_bytes,
            load_prompt("detect"),
            model,
            sleep,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000)
    objects = response.objects if response is not None else []
    return _save_result(method, seq, model, latency_ms, image, objects, output_dir, error)


async def _run_two_pass(
    detector: PromptDetector,
    image: np.ndarray,
    image_bytes: bytes,
    seq: int,
    model: str,
    output_dir: Path,
) -> BakeoffResult:
    started = time.perf_counter()
    objects: list[FrameVisionObject] = []
    error = None
    try:
        rows = await detector.detect_with_prompt(image_bytes, load_prompt("shelf_rows"), model)
        objects.extend(_label_boxes(rows.objects, "shelf_row"))
        height, width = image.shape[:2]
        for row in rows.objects:
            crop, bounds = _crop_box(image, row)
            if crop is None:
                continue
            ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                continue
            response = await detector.detect_with_prompt(
                encoded.tobytes(), load_prompt("spine_boxes"), model
            )
            objects.extend(_map_spines(response.objects, bounds, width, height))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        objects = []
    latency_ms = round((time.perf_counter() - started) * 1000)
    return _save_result(
        "spine-first-2pass", seq, model, latency_ms, image, objects, output_dir, error
    )


async def _detect_with_retry(
    detector: PromptDetector,
    image_bytes: bytes,
    prompt: str,
    model: str,
    sleep: Callable[[float], Awaitable[None]],
) -> FrameVisionResponse:
    for attempt in range(len(_RETRY_DELAYS_S) + 1):
        try:
            return await detector.detect_with_prompt(image_bytes, prompt, model)
        except Exception as exc:
            if (
                model != "gemini-3.8-flash"
                or not _is_server_error(exc)
                or attempt >= len(_RETRY_DELAYS_S)
            ):
                raise
            await sleep(_RETRY_DELAYS_S[attempt])
    raise RuntimeError("unreachable retry state")


def _is_server_error(error: Exception) -> bool:
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    if code in {500, 503}:
        return True
    message = str(error).upper()
    return "500" in message or "503" in message or "INTERNAL" in message or "UNAVAILABLE" in message


def _label_boxes(objects: list[FrameVisionObject], cls: str) -> list[FrameVisionObject]:
    return [item.model_copy(update={"cls": cls}) for item in objects]


def _crop_box(
    image: np.ndarray, box: FrameVisionObject
) -> tuple[np.ndarray | None, tuple[int, int, int, int]]:
    height, width = image.shape[:2]
    y0, x0, y1, x1 = _ordered_box(box.box_2d)
    pad_y, pad_x = round(height * 0.025), round(width * 0.01)
    left = max(0, round(x0 * width / 1000) - pad_x)
    right = min(width, round(x1 * width / 1000) + pad_x)
    top = max(0, round(y0 * height / 1000) - pad_y)
    bottom = min(height, round(y1 * height / 1000) + pad_y)
    if right - left < 8 or bottom - top < 8:
        return None, (left, top, right, bottom)
    return image[top:bottom, left:right], (left, top, right, bottom)


def _map_spines(
    objects: list[FrameVisionObject],
    bounds: tuple[int, int, int, int],
    width: int,
    height: int,
) -> list[FrameVisionObject]:
    left, top, right, bottom = bounds
    crop_width, crop_height = right - left, bottom - top
    mapped = []
    for item in objects:
        if item.cls != "book_spine":
            continue
        y0, x0, y1, x1 = _ordered_box(item.box_2d)
        full_box = [
            round((top + y0 * crop_height / 1000) * 1000 / height),
            round((left + x0 * crop_width / 1000) * 1000 / width),
            round((top + y1 * crop_height / 1000) * 1000 / height),
            round((left + x1 * crop_width / 1000) * 1000 / width),
        ]
        mapped.append(item.model_copy(update={"box_2d": full_box}))
    return mapped


def _ordered_box(box: list[int]) -> tuple[int, int, int, int]:
    y0, x0, y1, x1 = box
    return (
        max(0, min(1000, min(y0, y1))),
        max(0, min(1000, min(x0, x1))),
        max(0, min(1000, max(y0, y1))),
        max(0, min(1000, max(x0, x1))),
    )


def _save_result(
    method: str,
    seq: int,
    model: str,
    latency_ms: int,
    image: np.ndarray,
    objects: list[FrameVisionObject],
    output_dir: Path,
    error: str | None,
) -> BakeoffResult:
    annotated = image.copy()
    counts = Counter(item.cls for item in objects)
    for item in objects:
        y0, x0, y1, x1 = _ordered_box(item.box_2d)
        left, right = round(x0 * image.shape[1] / 1000), round(x1 * image.shape[1] / 1000)
        top, bottom = round(y0 * image.shape[0] / 1000), round(y1 * image.shape[0] / 1000)
        color = (0, 190, 255) if item.cls == "shelf_row" else (30, 220, 40)
        cv2.rectangle(annotated, (left, top), (right, bottom), color, 2)
        cv2.putText(
            annotated, item.cls, (left, max(18, top - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1
        )
    output_path = output_dir / method / f"f_{seq:06d}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), annotated)
    return BakeoffResult(
        method=method,
        seq=seq,
        model=model,
        latency_ms=latency_ms,
        counts=dict(sorted(counts.items())),
        output_path=output_path,
        error=error,
    )
