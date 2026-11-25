from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from app.capture.face_audit import create_face_contact_sheet
from PIL import Image


def test_face_contact_sheet_overlays_boxes_for_all_saved_frames(tmp_path: Path) -> None:
    sweep = tmp_path / "sweep"
    (sweep / "frames").mkdir(parents=True)
    first_frame = np.full((80, 100, 3), 220, dtype=np.uint8)
    Image.fromarray(first_frame).save(sweep / "frames" / "f_000000_0000000.jpg")
    Image.fromarray(first_frame).save(sweep / "frames" / "f_000001_0000300.jpg")
    records = [
        {
            "seq": 0,
            "t_ms": 0,
            "path": "frames/f_000000_0000000.jpg",
            "w": 100,
            "h": 80,
            "face_boxes": [[10, 12, 30, 35, 0.92]],
            "faces_blurred": 1,
        },
        {
            "seq": 1,
            "t_ms": 300,
            "path": "frames/f_000001_0000300.jpg",
            "w": 100,
            "h": 80,
            "face_boxes": [],
            "faces_blurred": 0,
        },
    ]
    (sweep / "frames.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )

    output = create_face_contact_sheet(sweep)

    assert output == sweep / "face_contact_sheet.jpg"
    assert output.is_file()
    with Image.open(output) as sheet:
        assert sheet.width > 0
        assert sheet.height > 0
