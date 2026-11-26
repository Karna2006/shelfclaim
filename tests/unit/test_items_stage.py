from __future__ import annotations

import json

from app.packet.models import BBox
from app.pipeline.artifacts import Detection, DetectionsDoc, FrameRecord
from app.pipeline.context import StageContext
from app.pipeline.stages.s08_items import run
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger


def test_item_stage_merges_nearby_detections_and_keeps_unknowns(tmp_path) -> None:
    (tmp_path / "frames").mkdir()
    frames = [
        FrameRecord(seq=1, t_ms=1000, path="frames/1.jpg", w=640, h=480, blur=200),
        FrameRecord(seq=2, t_ms=2000, path="frames/2.jpg", w=640, h=480, blur=400),
    ]
    (tmp_path / "frames.jsonl").write_text(
        "".join(frame.model_dump_json() + "\n" for frame in frames), encoding="utf-8"
    )
    detections = DetectionsDoc(
        frames={
            1: [
                Detection(
                    det_id="plant-1",
                    cls="item",
                    item_category="plant",
                    box_px=BBox(x=100, y=100, w=40, h=60),
                )
            ],
            2: [
                Detection(
                    det_id="plant-2",
                    cls="item",
                    item_category="plant",
                    box_px=BBox(x=104, y=103, w=40, h=60),
                ),
                Detection(
                    det_id="art-1",
                    cls="item",
                    item_category="framed_art",
                    box_px=BBox(x=300, y=100, w=80, h=80),
                ),
            ],
        }
    )
    (tmp_path / "s01_detections.json").write_text(detections.model_dump_json(), encoding="utf-8")
    context = StageContext(tmp_path, Settings(config=YamlSettings(), _env_file=None), Ledger())

    output = run(context)

    items = json.loads(output.read_text(encoding="utf-8"))["items"]
    assert len(items) == 2
    plant = next(item for item in items if item["category"] == "plant")
    assert plant["member_dets"] == ["plant-1", "plant-2"]
    assert plant["best_view"]["seq"] == 2
    assert plant["dimensions_cm"] == {"w": None, "h": None, "d": None}
    assert all(item["status"] == "needs_appraisal" for item in items)
