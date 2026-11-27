from __future__ import annotations

import json

from app.packet.models import Sweep
from app.pipeline.context import StageContext
from app.pipeline.stages.s10_assemble import run
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger


def _write(path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_packet_assembly_keeps_unknowns_null_and_reports_room_limit(tmp_path) -> None:
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames/f.jpg").write_bytes(b"saved frame")
    (tmp_path / "sweep.json").write_text(
        Sweep(
            id="sw_20261126_044135_a4bd",
            captured_at="2026-11-26T04:41:35+05:30",
            device="fixture",
            duration_s=0,
            country="IN",
            currency="INR",
            locale_config="config/locales/IN.yaml",
        ).model_dump_json(),
        encoding="utf-8",
    )
    _write(
        tmp_path / "s03_books_raw.json",
        {
            "units": [],
            "books": [
                {
                    "book_id": "b_0001",
                    "unit": "A",
                    "row": 1,
                    "position": 1,
                    "best_view": {
                        "seq": 0,
                        "frame_ref": "frames/f.jpg",
                        "bbox": {"x": 1, "y": 1, "w": 10, "h": 50, "angle_deg": 90},
                    },
                }
            ],
            "review_queue": [],
        },
    )
    _write(
        tmp_path / "s01_detections.json",
        {
            "review_queue": [
                {
                    "ref_id": "segment-2",
                    "code": "low_quality_coverage_segment",
                    "evidence": "Segment 2 had no QC-ok frame; selected frame 4.",
                }
            ]
        },
    )
    _write(tmp_path / "s04_measurements.json", {"books": {}, "rows": {}, "shelf_run_m": None})
    _write(tmp_path / "s05_transcriptions.json", {"books": {}})
    _write(
        tmp_path / "s06_identification.json",
        {
            "books": {
                "b_0001": {"status": "unidentified", "title": "", "authors": [], "id_confidence": 0}
            }
        },
    )
    quote = {
        "amount": None,
        "source": "",
        "url": "",
        "retrieved_at": "",
        "currency": "INR",
        "converted": False,
        "price_status": "not_found",
        "n_offers": 0,
        "snapshot_path": "",
    }
    _write(
        tmp_path / "s07_book_prices.json",
        {
            "books": {
                "b_0001": {
                    "new": quote,
                    "used": {**quote, "condition_assumed": "Used – Good"},
                    "appraisal": {"flag": False, "reasons": []},
                }
            },
            "review_queue": [],
        },
    )
    _write(tmp_path / "s08_items.json", {"items": []})
    _write(
        tmp_path / "s09_room.json",
        {
            "room": {
                "length_m": None,
                "width_m": None,
                "height_m": None,
                "floor_area_m2": None,
                "wall_area_m2": None,
                "shelved_wall_area_m2": None,
                "scale_method": "not measured (3D reconstruction out of scope for this build)",
                "confidence": 0,
                "shape": None,
                "coverage_pct": None,
            },
            "planes": {},
            "point_count": None,
        },
    )
    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        Ledger(),
    )

    packet_path = run(context)

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet["books"][0]["title"] == ""
    assert packet["books"][0]["spine_height_cm"] is None
    assert packet["room"]["floor_area_m2"] is None
    assert packet["room"]["confidence"] == 0
    assert any(entry["code"] == "room_not_measured" for entry in packet["review_queue"])
    assert any(
        entry["code"] == "low_quality_coverage_segment"
        and entry["ref_id"] == "segment-2"
        and entry["reason"] == "Low-quality coverage segment"
        for entry in packet["review_queue"]
    )
    assert packet["meta"]["validation"]["passed"] is True
    assert (tmp_path / "report.html").is_file()
