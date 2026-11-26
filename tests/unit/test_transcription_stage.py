from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from app.pipeline.context import StageContext
from app.pipeline.stages import s05_transcribe
from app.pipeline.stages.s05_transcribe import (
    _assign_lines_to_spines,
    _make_crops,
    _transcribe_batch,
    _transcribe_with_fallback,
    run,
)
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger
from app.vision.local_ocr import FrameOcrLine
from app.vision.schema import SpineLine, SpineTranscription, SpineTranscriptionResponse
from app.vision.transcription import CropInput
from pydantic import SecretStr


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

    assert fake.batch_sizes == [12, 1]
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


def test_book_crop_shrinks_box_width_and_uses_best_view(tmp_path) -> None:
    (tmp_path / "frames").mkdir()
    image = np.full((200, 200, 3), 120, dtype=np.uint8)
    assert cv2.imwrite(str(tmp_path / "frames/best.jpg"), image)
    book = {
        "book_id": "b_0001",
        "best_view": {
            "frame_ref": "frames/best.jpg",
            "bbox": {"x": 40, "y": 20, "w": 120, "h": 120, "angle_deg": 90},
        },
    }

    crops = _make_crops(tmp_path, {"books": [book]}, horizontal_shrink=0.10)

    assert len(crops) == 1
    decoded = cv2.imdecode(np.frombuffer(crops[0].image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[1] == 108
    assert crops[0].angle_deg == 90


def test_overlapping_spines_receive_only_lines_whose_centers_belong_to_them() -> None:
    books = [
        {
            "book_id": "b_0001",
            "best_view": {"bbox": {"x": 10, "y": 10, "w": 50, "h": 60}},
        },
        {
            "book_id": "b_0002",
            "best_view": {"bbox": {"x": 30, "y": 10, "w": 50, "h": 60}},
        },
    ]
    lines = [
        FrameOcrLine("FIRST SPINE", 0.9, 18, 20, 14, 8),
        FrameOcrLine("SECOND SPINE", 0.92, 59, 35, 14, 8),
        FrameOcrLine("OVERLAP NEAR SECOND", 0.88, 46, 50, 8, 8),
    ]

    assigned = _assign_lines_to_spines(lines, books)

    assert [line.text for line in assigned["b_0001"]] == ["FIRST SPINE"]
    assert [line.text for line in assigned["b_0002"]] == [
        "SECOND SPINE",
        "OVERLAP NEAR SECOND",
    ]


@pytest.mark.asyncio
async def test_local_ocr_uses_gemini_only_for_empty_crop(monkeypatch) -> None:
    class FakeLocalOcr:
        async def transcribe(self, crops):
            return SpineTranscriptionResponse(
                results=[
                    SpineTranscription(
                        crop_id=crop.crop_id,
                        readable=crop.crop_id == "readable_local",
                        lines=(
                            [SpineLine(text="VISIBLE TITLE", kind_guess="other")]
                            if crop.crop_id == "readable_local"
                            else []
                        ),
                        legibility=0.9 if crop.crop_id == "readable_local" else 0,
                    )
                    for crop in crops
                ]
            )

    class FakeGemini:
        calls: list[list[str]] = []
        closed = False

        def __init__(self, settings) -> None:
            del settings

        async def transcribe(self, crops, model: str) -> SpineTranscriptionResponse:
            del model
            self.calls.append([crop.crop_id for crop in crops])
            return SpineTranscriptionResponse(
                results=[
                    SpineTranscription(
                        crop_id=crop.crop_id,
                        readable=True,
                        lines=[SpineLine(text="FALLBACK TITLE", kind_guess="title")],
                        legibility=0.8,
                    )
                    for crop in crops
                ]
            )

        async def close(self) -> None:
            type(self).closed = True

    monkeypatch.setattr(s05_transcribe, "GeminiSpineTranscriber", FakeGemini)
    settings = Settings(
        config=YamlSettings(transcribe={"gemini_fallback_if_empty": True}),
        google_api_key=SecretStr("test-key"),
        _env_file=None,
    )
    context = StageContext(Path("."), settings, Ledger())
    crops = [CropInput("readable_local", b"a"), CropInput("empty_local", b"b")]

    result = await _transcribe_batch(crops, context, None, FakeLocalOcr())

    assert FakeGemini.calls == [["empty_local"]]
    assert FakeGemini.closed
    assert [row.lines[0].text for row in result.results] == ["VISIBLE TITLE", "FALLBACK TITLE"]
