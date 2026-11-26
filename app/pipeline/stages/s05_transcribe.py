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
from app.vision.local_ocr import FrameOcrLine, LocalOcrTranscriber
from app.vision.models import vision_model_chain
from app.vision.schema import SpineLine, SpineTranscription, SpineTranscriptionResponse
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
    transcriber_obj = ctx.clients.get("transcriber")
    if transcriber_obj is None and ctx.settings.config.transcribe.backend == "local_ocr":
        return await _run_frame_ocr(ctx, source_books, books)

    jobs = _make_crops(
        ctx.sweep_dir,
        {"books": source_books},
        ctx.settings.config.transcribe.crop_horizontal_shrink,
    )
    if not jobs:
        output = ctx.sweep_dir / "s05_transcriptions.json"
        output.write_text(json.dumps({"books": books}, indent=2) + "\n", encoding="utf-8")
        return output
    transcriber = cast(SpineTranscriber | None, transcriber_obj)
    local_ocr = None
    if transcriber is None and ctx.settings.config.transcribe.backend == "local_ocr":
        local_ocr = LocalOcrTranscriber(ctx.settings.config.transcribe.confidence_min)
    try:
        results: dict[str, list[dict[str, Any]]] = {}
        for start in range(0, len(jobs), 12):
            batch = jobs[start : start + 12]
            try:
                response = await _transcribe_batch(batch, ctx, transcriber, local_ocr)
            except RuntimeError as exc:
                write_event(
                    ctx.sweep_dir,
                    Event(
                        t_ms=0,
                        type="transcription_unavailable",
                        payload={"reason": str(exc), "crop_count": len(batch)},
                    ),
                )
                response = SpineTranscriptionResponse(results=[])
            known_ids = {crop.crop_id for crop in batch}
            for item in response.results:
                if item.crop_id not in known_ids:
                    continue
                book_id = item.crop_id.rsplit("_", 1)[0]
                view = item.model_dump(mode="json")
                view["crop_ref"] = f"evidence/crops/{item.crop_id}.jpg"
                results.setdefault(book_id, []).append(view)
    finally:
        if transcriber is not None and transcriber_obj is None:
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


async def _run_frame_ocr(
    ctx: StageContext, source_books: list[dict[str, Any]], books: dict[str, dict[str, Any]]
) -> Path:
    """Read each selected full frame once per rotation, then assign lines spatially."""
    transcriber = LocalOcrTranscriber(ctx.settings.config.transcribe.confidence_min)
    by_frame: dict[str, list[dict[str, Any]]] = {}
    for book in source_books:
        frame_ref = str(book.get("best_view", {}).get("frame_ref", ""))
        if frame_ref:
            by_frame.setdefault(frame_ref, []).append(book)

    for frame_ref, frame_books in by_frame.items():
        image = cv2.imread(str(ctx.sweep_dir / frame_ref))
        if image is None:
            continue
        include_upright = any(
            _is_flat(float(book["best_view"]["bbox"].get("angle_deg", 90))) for book in frame_books
        )
        lines = await transcriber.transcribe_frame(image, include_upright=include_upright)
        assigned = _assign_lines_to_spines(lines, frame_books)
        for book in frame_books:
            book_id = book["book_id"]
            own_lines = sorted(assigned.get(book_id, []), key=lambda line: line.center[1])
            spine_lines = [SpineLine(text=line.text) for line in own_lines]
            confidence = (
                sum(line.confidence for line in own_lines) / len(own_lines) if own_lines else 0
            )
            view = SpineTranscription(
                crop_id=f"{book_id}_frame",
                readable=bool(own_lines),
                orientation="frame_ocr",
                lines=spine_lines,
                legibility=confidence,
            ).model_dump(mode="json")
            view["lines"] = [
                {
                    "text": line.text,
                    "kind_guess": "other",
                    "confidence": line.confidence,
                    "bbox": {"x": line.x, "y": line.y, "w": line.w, "h": line.h},
                }
                for line in own_lines
            ]
            view["seq"] = book["best_view"].get("seq")
            view["frame_ref"] = frame_ref
            raw_text = " | ".join(line.text for line in own_lines)
            books[book_id] = {
                "views": [view],
                "consensus_text": raw_text,
                "legibility": confidence,
                "spine_text_raw": raw_text,
            }

    await _fallback_empty_books(ctx, source_books, books)
    output = ctx.sweep_dir / "s05_transcriptions.json"
    output.write_text(json.dumps({"books": books}, indent=2) + "\n", encoding="utf-8")
    return output


def _assign_lines_to_spines(
    lines: list[FrameOcrLine], books: list[dict[str, Any]]
) -> dict[str, list[FrameOcrLine]]:
    """Assign each text center to one containing spine, resolving overlap by x distance."""
    assigned: dict[str, list[FrameOcrLine]] = {book["book_id"]: [] for book in books}
    boxes = []
    for book in books:
        bbox = book["best_view"]["bbox"]
        boxes.append(
            (
                book["book_id"],
                float(bbox["x"]),
                float(bbox["y"]),
                float(bbox["w"]),
                float(bbox["h"]),
                float(bbox["x"]) + float(bbox["w"]) / 2,
            )
        )
    for line in lines:
        center_x, center_y = line.center
        containing = [
            box
            for box in boxes
            if box[1] <= center_x <= box[1] + box[3] and box[2] <= center_y <= box[2] + box[4]
        ]
        if containing:
            selected = min(containing, key=lambda box: (abs(box[5] - center_x), box[0]))
            assigned[selected[0]].append(line)
    return assigned


async def _fallback_empty_books(
    ctx: StageContext, source_books: list[dict[str, Any]], books: dict[str, dict[str, Any]]
) -> None:
    """Use the configured Gemini fallback only for books with no local frame text."""
    config = ctx.settings.config.transcribe
    if not config.gemini_fallback_if_empty or ctx.settings.google_api_key is None:
        return
    empty_ids = {book_id for book_id, result in books.items() if not result["spine_text_raw"]}
    fallback_books = [book for book in source_books if book["book_id"] in empty_ids]
    crops = _make_crops(ctx.sweep_dir, {"books": fallback_books}, config.crop_horizontal_shrink)
    if not crops:
        return
    gemini = GeminiSpineTranscriber(ctx.settings)
    try:
        response = await _transcribe_with_fallback(gemini, crops, ctx.settings.vision_model)
    except Exception as exc:
        write_event(
            ctx.sweep_dir,
            Event(
                t_ms=0,
                type="transcription_unavailable",
                payload={"reason": type(exc).__name__, "backend": "gemini_fallback"},
            ),
        )
        return
    finally:
        await gemini.close()
    for result in response.results:
        if not result.lines:
            continue
        book_id = result.crop_id.removesuffix("_local")
        raw_text = " | ".join(line.text for line in result.lines)
        books[book_id] = {
            "views": [result.model_dump(mode="json")],
            "consensus_text": raw_text,
            "legibility": result.legibility,
            "spine_text_raw": raw_text,
        }


def _is_flat(angle_deg: float) -> bool:
    angle = angle_deg % 180
    return min(angle, 180 - angle) < 45


async def _transcribe_batch(
    crops: list[CropInput],
    ctx: StageContext,
    injected: SpineTranscriber | None,
    local_ocr: LocalOcrTranscriber | None,
) -> SpineTranscriptionResponse:
    """Prefer local OCR, using Gemini only for empty OCR crops when enabled."""
    backend = ctx.settings.config.transcribe.backend
    if injected is not None:
        return await _transcribe_with_fallback(injected, crops, ctx.settings.vision_model)
    if backend == "gemini":
        gemini = GeminiSpineTranscriber(ctx.settings)
        try:
            return await _transcribe_with_fallback(gemini, crops, ctx.settings.vision_model)
        finally:
            await gemini.close()
    if local_ocr is None:
        raise RuntimeError("Local OCR backend was not initialized")

    local_result = await local_ocr.transcribe(crops)
    empty_ids = {row.crop_id for row in local_result.results if not row.lines}
    if (
        not empty_ids
        or not ctx.settings.config.transcribe.gemini_fallback_if_empty
        or ctx.settings.google_api_key is None
    ):
        return local_result

    gemini = GeminiSpineTranscriber(ctx.settings)
    try:
        fallback_crops = [crop for crop in crops if crop.crop_id in empty_ids]
        fallback = await gemini.transcribe(fallback_crops, ctx.settings.vision_model)
        replacements = {row.crop_id: row for row in fallback.results if row.lines}
        merged = [replacements.get(row.crop_id, row) for row in local_result.results]
        return SpineTranscriptionResponse(results=merged)
    except Exception as exc:
        write_event(
            ctx.sweep_dir,
            Event(
                t_ms=0,
                type="transcription_unavailable",
                payload={
                    "reason": f"{type(exc).__name__}",
                    "crop_count": len(empty_ids),
                    "backend": "gemini_fallback",
                },
            ),
        )
        return local_result
    finally:
        await gemini.close()


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


def _make_crops(
    sweep_dir: Path, raw: dict[str, Any], horizontal_shrink: float = 0.10
) -> list[CropInput]:
    crops: list[CropInput] = []
    crop_dir = sweep_dir / "evidence" / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for book in raw.get("books", []):
        view = book["best_view"]
        image = cv2.imread(str(sweep_dir / view["frame_ref"]))
        if image is None:
            continue
        box = view["bbox"]
        shrink = min(round(box["w"] * horizontal_shrink), max(0, (box["w"] - 1) // 2))
        left_shrink = shrink // 2
        right_shrink = shrink - left_shrink
        x0 = max(0, box["x"] + left_shrink)
        y0 = max(0, box["y"])
        x1 = min(image.shape[1], box["x"] + box["w"] - right_shrink)
        y1 = min(image.shape[0], y0 + box["h"])
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        short = min(crop.shape[:2])
        if short < 96:
            scale = 96 / short
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        crop_id = f"{book['book_id']}_local"
        ok, encoded = cv2.imencode(".jpg", crop)
        if not ok:
            continue
        (crop_dir / f"{crop_id}.jpg").write_bytes(encoded.tobytes())
        crops.append(CropInput(crop_id, encoded.tobytes(), float(box.get("angle_deg", 90))))
    return crops
