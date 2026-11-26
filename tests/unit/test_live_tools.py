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
    assert status["coverage"] == "not yet calculated"
