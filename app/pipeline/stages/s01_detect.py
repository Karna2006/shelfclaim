"""Detect and consolidate objects on selected sharp sweep keyframes.

Input: saved frames, vision detector interface and configured rules. Output:
`s01_detections.json`; model hints remain diagnostic, never packet counts.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from pathlib import Path
from typing import Literal, cast

import cv2
import numpy as np
from app.capture.storage import list_frames
from app.live.rate_limit import ModelRateLimiter
from app.packet.models import BBox
from app.pipeline.artifacts import (
    Detection,
    DetectionFrameStats,
    DetectionReviewEntry,
    DetectionsDoc,
    Event,
    SelectedDetectionKeyframe,
)
from app.pipeline.context import StageContext
from app.settings import Settings
from app.telemetry.events import write_event
from app.vision.client import GeminiVisionDetector, VisionDetector
from app.vision.keyframes import describe_explicit_selection, select_detection_keyframes
from app.vision.local_ocr import LocalOcrTranscriber
from app.vision.models import vision_model_chain
from app.vision.nms import suppress_frame_duplicates
from app.vision.ocr_detection import detections_from_ocr
from app.vision.schema import VisionResponse

_ALLOWED_CLASSES = {
    "book_spine",
    "book_stack",
    "shelf_board",
    "shelf_unit",
    "item",
    "room_landmark",
    "person_present",
}


async def run(
    ctx: StageContext,
    *,
    max_keyframes: int | None = None,
    frame_seqs: tuple[int, ...] | None = None,
) -> Path:
    """Run S1 with OCR-first detections and an optional Gemini assist."""
    injected = ctx.clients.get("vision")
    backend = ctx.settings.config.detection.backend
    needs_gemini = backend == "gemini" or ctx.settings.config.detection.assist == "gemini"
    detector = cast(VisionDetector | None, injected) if injected is not None else None
    owns_detector = detector is None and needs_gemini
    assist_error = None
    if owns_detector:
        try:
            detector = GeminiVisionDetector(ctx.settings)
        except Exception as exc:
            if backend == "gemini":
                raise
            assist_error = f"{type(exc).__name__}: {exc}"
    try:
        return await run_detection_stage(
            ctx.sweep_dir,
            ctx.settings,
            detector,
            backend=backend,
            assist_error=assist_error,
            ocr=cast(LocalOcrTranscriber | None, ctx.clients.get("local_ocr")),
            max_frames=max_keyframes,
            frame_seqs=frame_seqs,
        )
    finally:
        if owns_detector and detector is not None:
            await detector.close()


async def run_detection_stage(
    sweep_dir: Path,
    settings: Settings,
    detector: VisionDetector | None = None,
    *,
    backend: Literal["ocr_spines", "gemini"] = "gemini",
    assist_error: str | None = None,
    ocr: LocalOcrTranscriber | None = None,
    limiter: ModelRateLimiter | None = None,
    max_frames: int | None = None,
    frame_seqs: tuple[int, ...] | None = None,
) -> Path:
    """Select and detect keyframes with concurrency two and bounded 429 retries."""
    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames must be positive")
    configured_max = settings.config.detection.max_keyframes
    selected_max = min(max_frames, configured_max) if max_frames is not None else configured_max
    available_frames = list_frames(sweep_dir)
    if frame_seqs is None:
        selection = select_detection_keyframes(
            sweep_dir,
            max_frames=selected_max,
        )
    else:
        by_seq = {frame.seq: frame for frame in available_frames}
        if len(frame_seqs) != len(set(frame_seqs)) or any(seq not in by_seq for seq in frame_seqs):
            raise ValueError("frame_seqs must contain unique saved frame sequences")
        if len(frame_seqs) > selected_max:
            raise ValueError("frame_seqs cannot exceed the selected keyframe limit")
        keyframes = [by_seq[seq] for seq in frame_seqs]
        selection = describe_explicit_selection(
            available_frames, keyframes, segment_count=selected_max
        )
    keyframes = selection.frames
    if backend == "gemini" and detector is None:
        raise ValueError("Gemini backend requires a vision detector")
    if backend == "ocr_spines" and ocr is None:
        ocr = LocalOcrTranscriber(settings.config.detection.ocr_confidence_min)
    limiter = limiter or ModelRateLimiter(settings.config.llm)
    semaphore = asyncio.Semaphore(2)
    ocr_semaphore = asyncio.Semaphore(1)

    async def detect_one(record: object) -> tuple[int, list[Detection], DetectionFrameStats]:
        frame = record
        image_path = sweep_dir / frame.path
        data = image_path.read_bytes()
        errors: list[str] = []
        if backend == "ocr_spines" and assist_error:
            errors.append(f"gemini_assist_unavailable: {assist_error}")
        if backend == "ocr_spines":
            if ocr is None:
                raise RuntimeError("OCR detector was not initialized")
            started = time.perf_counter()
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"Could not decode saved frame {frame.path}")
            async with ocr_semaphore:
                ocr_lines = await ocr.transcribe_frame(image, include_upright=True)
            raw = detections_from_ocr(
                frame.seq,
                ocr_lines,
                frame.w,
                frame.h,
                confidence_min=settings.config.detection.ocr_confidence_min,
                min_spine_height_pct=settings.config.detection.ocr_min_spine_height_pct,
                vertical_aspect_min=settings.config.detection.ocr_vertical_aspect_min,
                flat_line_width_pct=settings.config.detection.ocr_flat_line_width_pct,
                row_gap_factor=settings.config.detection.ocr_row_gap_factor,
                x_eps_factor=settings.config.detection.ocr_x_eps_factor,
                max_cluster_width_pct_row=(settings.config.detection.ocr_max_cluster_width_pct_row),
            )
            model = "rapidocr-onnxruntime"
            latency_ms = round((time.perf_counter() - started) * 1000)
            if settings.config.detection.assist == "gemini" and detector is not None:
                try:
                    response, assist_model, assist_latency = await _detect_with_retry(
                        detector, limiter, settings, data, semaphore
                    )
                    assist_boxes = _unmatched_gemini_spines(
                        frame.seq, response, raw, frame.w, frame.h
                    )
                    raw.extend(assist_boxes)
                    model = f"{model}+{assist_model}"
                    latency_ms += assist_latency
                except Exception as exc:
                    errors.append(f"gemini_assist: {type(exc).__name__}: {exc}")
            elif settings.config.detection.assist == "gemini" and not assist_error:
                errors.append("gemini_assist_unavailable: detector client is unavailable")
        else:
            if detector is None:
                raise RuntimeError("Gemini detector was not initialized")
            response, model, latency_ms = await _detect_with_retry(
                detector, limiter, settings, data, semaphore
            )
            raw = [
                detection
                for index, item in enumerate(response.objects)
                if item.cls in _ALLOWED_CLASSES
                if (detection := _to_detection(frame.seq, index, item, frame.w, frame.h))
                is not None
            ]
        kept = suppress_frame_duplicates(raw, settings.config.dedup)
        counts = Counter(item.cls for item in kept)
        stats = DetectionFrameStats(
            seq=frame.seq,
            model=model,
            latency_ms=latency_ms,
            spine_count=counts.get("book_spine", 0),
            shelf_board_count=counts.get("shelf_board", 0),
            item_count=counts.get("item", 0),
            errors=errors,
        )
        return frame.seq, kept, stats

    results = await asyncio.gather(*(detect_one(row) for row in keyframes))
    document = DetectionsDoc(
        backend=backend,
        frames={seq: detections for seq, detections, _ in results},
        keyframe_stats=[stats for _, _, stats in results],
        selected_keyframes=[
            SelectedDetectionKeyframe(
                seq=choice.frame.seq,
                segment=choice.segment,
                qc_verdict=choice.frame.qc_verdict,
                blur=choice.frame.blur,
                quality_fallback=choice.quality_fallback,
            )
            for choice in selection.choices
            if choice.frame is not None
        ],
        review_queue=[
            DetectionReviewEntry(
                ref_id=f"segment-{choice.segment + 1}",
                code="low_quality_coverage_segment",
                evidence=(
                    f"Segment {choice.segment + 1} had no saved frames."
                    if choice.frame is None
                    else (
                        f"Segment {choice.segment + 1} had no QC-ok frame; "
                        f"selected frame {choice.frame.seq} (verdict={choice.frame.qc_verdict}, "
                        f"blur={choice.frame.blur})."
                    )
                ),
            )
            for choice in selection.review_choices
        ],
    )
    output = sweep_dir / "s01_detections.json"
    output.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
    write_event(
        sweep_dir,
        Event(
            t_ms=keyframes[-1].t_ms if keyframes else 0,
            type="stage_done",
            payload={
                "stage": "s01",
                "keyframes": len(keyframes),
                "detections": sum(map(len, document.frames.values())),
            },
        ),
    )
    return output


async def _detect_with_retry(
    detector: VisionDetector,
    limiter: ModelRateLimiter,
    settings: Settings,
    image: bytes,
    semaphore: asyncio.Semaphore,
) -> tuple[VisionResponse, str, int]:
    total_request_s = 0.0
    failures: list[str] = []
    async with semaphore:
        primary = settings.config.vision.detection_model
        model_chain = (
            vision_model_chain(primary)
            if settings.config.vision.detection_model_fallbacks
            else (primary,)
        )
        for model in model_chain:
            retry = limiter.settings_for(model)
            attempt = 0
            while True:
                await limiter.acquire(model)
                request_started = time.perf_counter()
                try:
                    response = await detector.detect(image, model)
                    total_request_s += time.perf_counter() - request_started
                    return response, model, round(total_request_s * 1000)
                except Exception as exc:
                    total_request_s += time.perf_counter() - request_started
                    retry_429 = _is_429(exc) and attempt < retry.max_retries
                    retry_503 = _is_503(exc) and attempt < 1
                    if retry_429 or retry_503:
                        await asyncio.sleep(limiter.backoff_s(model, attempt))
                        attempt += 1
                        continue
                    failures.append(f"{model}: {type(exc).__name__} ({_status_code(exc)})")
                    break
    raise RuntimeError("All vision models failed: " + "; ".join(failures))


def _to_detection(seq: int, index: int, item: object, width: int, height: int) -> Detection | None:
    ymin, xmin, ymax, xmax = item.box_2d
    x0, x1 = sorted((max(0, min(1000, xmin)), max(0, min(1000, xmax))))
    y0, y1 = sorted((max(0, min(1000, ymin)), max(0, min(1000, ymax))))
    left, right = round(x0 * width / 1000), round(x1 * width / 1000)
    top, bottom = round(y0 * height / 1000), round(y1 * height / 1000)
    left, top = min(width - 1, left), min(height - 1, top)
    box_w, box_h = min(width - left, max(1, right - left)), min(height - top, max(1, bottom - top))
    return Detection(
        det_id=f"f{seq:06d}_d{index:04d}",
        cls=item.cls,
        box_px=BBox(x=left, y=top, w=box_w, h=box_h, angle_deg=item.angle_deg),
        item_category=item.item_category or item.note,
    )


def _unmatched_gemini_spines(
    seq: int,
    response: VisionResponse,
    ocr_detections: list[Detection],
    width: int,
    height: int,
) -> list[Detection]:
    """Keep only assist boxes with no spatial overlap with an OCR spine cluster."""
    extras = []
    for index, item in enumerate(response.objects):
        if item.cls != "book_spine":
            continue
        candidate = _to_detection(seq, index, item, width, height)
        if candidate is None:
            continue
        if any(
            _box_overlap_fraction(candidate.box_px, known.box_px) > 0 for known in ocr_detections
        ):
            continue
        if ocr_detections:
            nearest = min(
                ocr_detections,
                key=lambda known: abs(_center_y(known) - _center_y(candidate)),
            )
            candidate.row_index = nearest.row_index
        else:
            candidate.row_index = 1
        candidate.flags.append("gemini_assist_unreadable")
        extras.append(candidate)
    return extras


def _box_overlap_fraction(first: BBox, second: BBox) -> float:
    left, top = max(first.x, second.x), max(first.y, second.y)
    right = min(first.x + first.w, second.x + second.w)
    bottom = min(first.y + first.h, second.y + second.h)
    intersection = max(0, right - left) * max(0, bottom - top)
    smaller = min(first.w * first.h, second.w * second.h)
    return intersection / smaller if smaller else 0.0


def _center_y(detection: Detection) -> float:
    return detection.box_px.y + detection.box_px.h / 2


def _is_429(error: Exception) -> bool:
    return (
        getattr(error, "code", None) == 429
        or getattr(error, "status_code", None) == 429
        or "429" in str(error)
    )


def _is_503(error: Exception) -> bool:
    return _status_code(error) == 503 or "503" in str(error)


def _status_code(error: Exception) -> int | None:
    for attribute in ("code", "status_code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    return None
