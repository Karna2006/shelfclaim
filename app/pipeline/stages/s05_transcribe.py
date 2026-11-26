"""Crop and transcribe S3 book views in bounded batches.

Input: best-view detections and saved image files. Output: `s05_transcriptions.json`;
every identity clue remains verbatim transcription evidence, not model memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import cv2
from app.pipeline.artifacts import Event
from app.pipeline.context import StageContext
from app.telemetry.events import write_event
from app.vision.models import vision_model_chain
from app.vision.schema import SpineTranscriptionResponse
from app.vision.transcription import CropInput, GeminiSpineTranscriber, SpineTranscriber


async def run(ctx: StageContext, *, max_books: int | None = None) -> Path:
    """Write visible spine text using injected or configured transcription service."""
    if max_books is not None and max_books < 1:
        raise ValueError("max_books must be positive")
    s03 = ctx.sweep_dir / "s03_books_raw.json"
    if not s03.is_file():
        raise FileNotFoundError("S3 book clusters are required before transcription")
    raw = json.loads(s03.read_text(encoding="utf-8"))
    source_books = raw.get("books", [])
    if max_books is not None:
        source_books = source_books[:max_books]
    books = {
        book["book_id"]: {
            "views": [],
            "consensus_text": "",
            "legibility": 0,
            "spine_text_raw": "",
        }
        for book in source_books
    }
    jobs = _make_crops(ctx.sweep_dir, {"books": source_books})
    if not jobs:
        output = ctx.sweep_dir / "s05_transcriptions.json"
        output.write_text(json.dumps({"books": books}, indent=2) + "\n", encoding="utf-8")
        return output
    transcriber_obj = ctx.clients.get("transcriber")
    transcriber = (
        cast(SpineTranscriber, transcriber_obj)
        if transcriber_obj
        else GeminiSpineTranscriber(ctx.settings)
    )
    try:
        results: dict[str, list[dict[str, Any]]] = {}
        for start in range(0, len(jobs), 12):
            batch = jobs[start : start + 12]
            try:
                response = await _transcribe_with_fallback(
                    transcriber, batch, ctx.settings.vision_model
                )
            except RuntimeError as exc:
                write_event(
                    ctx.sweep_dir,
                    Event(
                        t_ms=0,
                        type="transcription_unavailable",
                        payload={"reason": str(exc), "crop_count": len(batch)},
                    ),
                )
                continue
            known_ids = {crop.crop_id for crop in batch}
            for item in response.results:
                if item.crop_id not in known_ids:
                    continue
                book_id = item.crop_id.rsplit("_", 1)[0]
                view = item.model_dump(mode="json")
                view["crop_ref"] = f"evidence/crops/{item.crop_id}.jpg"
                results.setdefault(book_id, []).append(view)
    finally:
        if transcriber_obj is None:
            await transcriber.close()
    for book_id, views in results.items():
        best = max(views, key=lambda view: (view["readable"], view["legibility"]))
        raw_text = " | ".join(line["text"] for line in best["lines"])
        books[book_id] = {
            "views": views,
            "consensus_text": raw_text,
            "legibility": best["legibility"],
            "spine_text_raw": raw_text,
        }
    output = ctx.sweep_dir / "s05_transcriptions.json"
    output.write_text(json.dumps({"books": books}, indent=2) + "\n", encoding="utf-8")
    return output


async def _transcribe_with_fallback(
    transcriber: SpineTranscriber,
    crops: list[CropInput],
    primary_model: str,
) -> SpineTranscriptionResponse:
    """Try configured vision models in order so an exhausted primary can fall back."""
    failures = []
    for model in vision_model_chain(primary_model):
        try:
            return await transcriber.transcribe(crops, model)
        except Exception as exc:
            failures.append(f"{model}: {type(exc).__name__}")
    raise RuntimeError("All transcription models failed: " + "; ".join(failures))


def _make_crops(sweep_dir: Path, raw: dict[str, Any]) -> list[CropInput]:
    crops: list[CropInput] = []
    crop_dir = sweep_dir / "evidence" / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for book in raw.get("books", []):
        view = book["best_view"]
        image = cv2.imread(str(sweep_dir / view["frame_ref"]))
        if image is None:
            continue
        box = view["bbox"]
        x0, y0 = max(0, box["x"]), max(0, box["y"])
        x1, y1 = min(image.shape[1], x0 + box["w"]), min(image.shape[0], y0 + box["h"])
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        rotations = [("upright", crop)]
        if abs(float(box.get("angle_deg", 90))) % 180 > 45:
            rotations = [
                ("cw", cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)),
                ("ccw", cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)),
            ]
        for orientation, rotated in rotations:
            short = min(rotated.shape[:2])
            if short < 96:
                scale = 96 / short
                rotated = cv2.resize(
                    rotated, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
                )
            crop_id = f"{book['book_id']}_{orientation}"
            ok, encoded = cv2.imencode(".jpg", rotated)
            if not ok:
                continue
            (crop_dir / f"{crop_id}.jpg").write_bytes(encoded.tobytes())
            crops.append(CropInput(crop_id, encoded.tobytes()))
    return crops
