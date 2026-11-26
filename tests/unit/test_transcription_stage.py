from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from app.pipeline.context import StageContext
from app.pipeline.stages.s05_transcribe import run
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger
from app.vision.schema import SpineTranscription, SpineTranscriptionResponse


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
