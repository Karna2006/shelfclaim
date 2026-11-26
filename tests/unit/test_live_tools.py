from __future__ import annotations

import json
from pathlib import Path

from app.live.session import LiveSessionContext
from app.live.tools import ToolHandlers
from app.packet.models import Sweep
from app.settings import Settings, YamlSettings


def test_tool_handlers_validate_locale_and_return_stub_status(tmp_path: Path) -> None:
    sweep = Sweep(
        id="sw_20261126_030042_1552",
        captured_at="2026-11-26T03:00:42+05:30",
        device="test",
        duration_s=0,
        country="IN",
        currency="INR",
        locale_config="config/locales/IN.yaml",
    )
    (tmp_path / "sweep.json").write_text(sweep.model_dump_json(), encoding="utf-8")
    settings = Settings(config=YamlSettings(), sweeps_dir=tmp_path, _env_file=None)
    session = LiveSessionContext(sweep.id, tmp_path)
    handlers = ToolHandlers(settings, session)

    locale = handlers._set_locale({"country": "GB", "currency": "GBP"})
    status = handlers._get_sweep_status({})

    saved = json.loads((tmp_path / "sweep.json").read_text(encoding="utf-8"))
    assert locale == {"supported": True, "country": "GB", "currency": "GBP"}
    assert saved["country"] == "GB"
    assert status["coverage"]["available"] is False
    assert status["coverage"]["frames_seen"] == 0


def test_end_sweep_requests_coverage_confirmation_when_unavailable(tmp_path: Path) -> None:
    sweep = Sweep(
        id="sw_20261126_030042_1552",
        captured_at="2026-11-26T03:00:42+05:30",
        device="test",
        duration_s=0,
        country="IN",
        currency="INR",
        locale_config="config/locales/IN.yaml",
    )
    (tmp_path / "sweep.json").write_text(sweep.model_dump_json(), encoding="utf-8")
    session = LiveSessionContext(sweep.id, tmp_path)
    handlers = ToolHandlers(Settings(config=YamlSettings(), _env_file=None), session)

    waiting = handlers._end_sweep({})
    assert waiting["stopped"] is False
    assert "all shelves" in waiting["ask_user"]

    session.latest_user_text = "No rows missed, that's all"
    stopped = handlers._end_sweep({})
    assert stopped["stopped"] is True


def test_sweep_status_reports_shelf_rows_and_provisional_counts(tmp_path: Path) -> None:
    sweep = Sweep(
        id="sw_20261126_030042_1552",
        captured_at="2026-11-26T03:00:42+05:30",
        device="test",
        duration_s=0,
        country="IN",
        currency="INR",
        locale_config="config/locales/IN.yaml",
    )
    (tmp_path / "sweep.json").write_text(sweep.model_dump_json(), encoding="utf-8")
    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps(
            {
                "units": [{"unit": "A", "rows": [{"row": 1, "count": 7, "best_frame_seq": 4}]}],
                "review_queue": [],
            }
        ),
        encoding="utf-8",
    )
    handlers = ToolHandlers(
        Settings(config=YamlSettings(), _env_file=None),
        LiveSessionContext(sweep.id, tmp_path),
    )

    result = handlers._get_sweep_status({})

    assert result["coverage"]["units_seen"] == 1
    assert result["coverage"]["rows_seen"] == 1
    assert result["coverage"]["provisional_counts"] == [
        {"row": "A-1", "books": 7, "best_frame_seq": 4}
    ]
