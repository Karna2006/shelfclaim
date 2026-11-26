"""Detect and consolidate objects on selected sharp sweep keyframes.

Input: saved frames, vision detector interface and configured rules. Output:
`s01_detections.json`; model hints remain diagnostic, never packet counts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from app.live.rate_limit import ModelRateLimiter
from app.pipeline.artifacts import Detection, DetectionsDoc, Event
from app.pipeline.context import StageContext
from app.settings import Settings
from app.telemetry.events import write_event
from app.vision.client import GeminiVisionDetector, VisionDetector
from app.vision.keyframes import select_detection_keyframes
from app.vision.nms import suppress_frame_duplicates
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


async def run(ctx: StageContext) -> Path:
    """Run S1 using a supplied fake/client or the configured Gemini client."""
    injected = ctx.clients.get("vision")
    detector = (
        cast(VisionDetector, injected)
        if injected is not None
        else GeminiVisionDetector(ctx.settings)
    )
    try:
        return await run_detection_stage(ctx.sweep_dir, ctx.settings, detector)
    finally:
        if injected is None:
            await detector.close()


async def run_detection_stage(
    sweep_dir: Path,
    settings: Settings,
    detector: VisionDetector,
    *,
    limiter: ModelRateLimiter | None = None,
) -> Path:
    """Select and detect keyframes with concurrency two and bounded 429 retries."""
    keyframes = select_detection_keyframes(sweep_dir, settings.config.keyframes)
    limiter = limiter or ModelRateLimiter(settings.config.llm)
    semaphore = asyncio.Semaphore(2)

    async def detect_one(record: object) -> tuple[int, list[Detection]]:
        frame = record
        image_path = sweep_dir / frame.path
        data = image_path.read_bytes()
        response = await _detect_with_retry(detector, limiter, settings, data, semaphore)
        raw = [
            detection
            for index, item in enumerate(response.objects)
            if item.cls in _ALLOWED_CLASSES
            if (detection := _to_detection(frame.seq, index, item, frame.w, frame.h)) is not None
        ]
        return frame.seq, suppress_frame_duplicates(raw, settings.config.dedup)

    results = await asyncio.gather(*(detect_one(row) for row in keyframes))
    document = DetectionsDoc(frames={seq: detections for seq, detections in results})
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
) -> VisionResponse:
    model = settings.vision_model
    retry = limiter.settings_for(model)
    async with semaphore:
        for attempt in range(retry.max_retries + 1):
            await limiter.acquire(model)
            try:
                return await detector.detect(image, model)
            except Exception as exc:
                if not _is_429(exc) or attempt >= retry.max_retries:
                    raise
                await asyncio.sleep(limiter.backoff_s(model, attempt))
    raise RuntimeError("unreachable detection retry state")


def _to_detection(seq: int, index: int, item: object, width: int, height: int) -> Detection | None:
    ymin, xmin, ymax, xmax = item.box_2d
    x0, x1 = sorted((max(0, min(1000, xmin)), max(0, min(1000, xmax))))
    y0, y1 = sorted((max(0, min(1000, ymin)), max(0, min(1000, ymax))))
    left, right = round(x0 * width / 1000), round(x1 * width / 1000)
    top, bottom = round(y0 * height / 1000), round(y1 * height / 1000)
    left, top = min(width - 1, left), min(height - 1, top)
    box_w, box_h = min(width - left, max(1, right - left)), min(height - top, max(1, bottom - top))
    from app.packet.models import BBox

    return Detection(
        det_id=f"f{seq:06d}_d{index:04d}",
        cls=item.cls,
        box_px=BBox(x=left, y=top, w=box_w, h=box_h, angle_deg=item.angle_deg),
        item_category=item.item_category or item.note,
    )


def _is_429(error: Exception) -> bool:
    return (
        getattr(error, "code", None) == 429
        or getattr(error, "status_code", None) == 429
        or "429" in str(error)
    )
