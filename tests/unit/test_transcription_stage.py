from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from app.pipeline.context import StageContext
from app.pipeline.stages.s05_transcribe import _transcribe_with_fallback, run
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger
from app.vision.schema import SpineTranscription, SpineTranscriptionResponse
from app.vision.transcription import CropInput


class FakeTranscriber:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    async def transcribe(self, crops, model: str) -> SpineTranscriptionResponse:
        self.batch_sizes.append(len(crops))
        return SpineTranscriptionResponse(
            results=[
                SpineTranscription(crop_id=crop.crop_id, readable=False, legibility=0)
                for crop in crops
            ]
        )


@pytest.mark.asyncio
async def test_transcription_stage_batches_no_more_than_twelve_crops(tmp_path) -> None:
    (tmp_path / "frames").mkdir()
    image = np.full((80, 80, 3), 150, dtype=np.uint8)
    assert cv2.imwrite(str(tmp_path / "frames/frame.jpg"), image)
    books = [
        {
            "book_id": f"b_{index:04d}",
            "best_view": {
                "frame_ref": "frames/frame.jpg",
                "bbox": {"x": 10, "y": 10, "w": 10, "h": 40, "angle_deg": 90},
            },
        }
        for index in range(13)
    ]
    (tmp_path / "s03_books_raw.json").write_text(json.dumps({"books": books}), encoding="utf-8")
    fake = FakeTranscriber()
    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        Ledger(),
        {"transcriber": fake},
    )

    output = await run(context)

    assert fake.batch_sizes == [12, 12, 2]
    assert len(json.loads(output.read_text(encoding="utf-8"))["books"]) == 13


@pytest.mark.asyncio
async def test_transcription_limit_keeps_empty_placeholder_for_unreadable_book(tmp_path) -> None:
    books = [
        {"book_id": "b_0001", "best_view": {"frame_ref": "missing.jpg", "bbox": {}}},
        {"book_id": "b_0002", "best_view": {"frame_ref": "missing.jpg", "bbox": {}}},
    ]
    (tmp_path / "s03_books_raw.json").write_text(json.dumps({"books": books}), encoding="utf-8")
    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        Ledger(),
    )

    output = await run(context, max_books=1)

    transcriptions = json.loads(output.read_text(encoding="utf-8"))["books"]
    assert list(transcriptions) == ["b_0001"]
    assert transcriptions["b_0001"]["spine_text_raw"] == ""
    assert transcriptions["b_0001"]["views"] == []


@pytest.mark.asyncio
async def test_transcription_falls_back_after_primary_model_quota_error() -> None:
    class QuotaFallbackTranscriber:
        def __init__(self) -> None:
            self.models = []

        async def transcribe(self, crops, model: str) -> SpineTranscriptionResponse:
            del crops
            self.models.append(model)
            if model == "gemini-3.8-flash":
                raise RuntimeError("quota exhausted")
            return SpineTranscriptionResponse(results=[])

    fake = QuotaFallbackTranscriber()

    result = await _transcribe_with_fallback(
        fake, [CropInput("book_upright", b"image")], "gemini-3.8-flash"
    )

    assert result.results == []
    assert fake.models == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


@pytest.mark.asyncio
async def test_transcription_quota_exhaustion_keeps_unknown_placeholder(tmp_path) -> None:
    (tmp_path / "frames").mkdir()
    image = np.full((120, 120, 3), 100, dtype=np.uint8)
    assert cv2.imwrite(str(tmp_path / "frames/frame.jpg"), image)
    books = [
        {
            "book_id": "b_0001",
            "best_view": {
                "frame_ref": "frames/frame.jpg",
                "bbox": {"x": 10, "y": 10, "w": 20, "h": 80, "angle_deg": 90},
            },
        }
    ]
    (tmp_path / "s03_books_raw.json").write_text(json.dumps({"books": books}), encoding="utf-8")

    class ExhaustedTranscriber:
        async def transcribe(self, crops, model: str) -> SpineTranscriptionResponse:
            del crops
            raise RuntimeError(f"{model} quota exhausted")

    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), vision_model="gemini-3.8-flash", _env_file=None),
        Ledger(),
        {"transcriber": ExhaustedTranscriber()},
    )

    output = await run(context)

    result = json.loads(output.read_text(encoding="utf-8"))["books"]["b_0001"]
    assert result["spine_text_raw"] == ""
    assert result["views"] == []
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["type"] == "transcription_unavailable"
