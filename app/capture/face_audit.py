"""Build a contact sheet for reviewing face redaction during a sweep.

Input is a sweep's saved frames and `frames.jsonl`; output is one labelled JPEG.
Implements the capture audit described in `docs/05_DATA_SCHEMA.md` §2.
"""

from __future__ import annotations

from pathlib import Path

from app.capture.storage import list_frames
from PIL import Image, ImageDraw, ImageOps

_COLUMNS = 4
_THUMBNAIL_WIDTH = 320
_THUMBNAIL_HEIGHT = 200
_LABEL_HEIGHT = 24
_GAP = 8


def create_face_contact_sheet(sweep: Path, output: Path | None = None) -> Path:
    """Save all sweep frames with face-box overlays and sequence labels."""
    records = list_frames(sweep)
    if not records:
        raise ValueError(f"No frame records found in sweep: {sweep}")

    columns = min(_COLUMNS, len(records))
    rows = (len(records) + columns - 1) // columns
    cell_width = _THUMBNAIL_WIDTH
    cell_height = _THUMBNAIL_HEIGHT + _LABEL_HEIGHT
    sheet = Image.new(
        "RGB",
        (columns * cell_width + (columns + 1) * _GAP, rows * cell_height + (rows + 1) * _GAP),
        "white",
    )
    draw = ImageDraw.Draw(sheet)

    for index, record in enumerate(records):
        frame_path = sweep / record.path
        with Image.open(frame_path) as source:
            image = ImageOps.contain(source.convert("RGB"), (_THUMBNAIL_WIDTH, _THUMBNAIL_HEIGHT))
        column, row = index % columns, index // columns
        cell_x = _GAP + column * (cell_width + _GAP)
        cell_y = _GAP + row * (cell_height + _GAP)
        image_x = cell_x + (_THUMBNAIL_WIDTH - image.width) // 2
        image_y = cell_y + (_THUMBNAIL_HEIGHT - image.height) // 2
        sheet.paste(image, (image_x, image_y))
        scale_x, scale_y = image.width / record.w, image.height / record.h
        for x, y, width, height, score in record.face_boxes:
            box = (
                image_x + round(x * scale_x),
                image_y + round(y * scale_y),
                image_x + round((x + width) * scale_x),
                image_y + round((y + height) * scale_y),
            )
            draw.rectangle(box, outline="red", width=3)
            score_text = "score n/a" if score is None else f"{score:.2f}"
            draw.text((box[0], max(image_y, box[1] - 14)), score_text, fill="red")
        draw.text(
            (cell_x, cell_y + _THUMBNAIL_HEIGHT + 2),
            f"Frame {record.seq} · {len(record.face_boxes)} face(s)",
            fill="black",
        )

    destination = output or sweep / "face_contact_sheet.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="JPEG", quality=90)
    return destination
