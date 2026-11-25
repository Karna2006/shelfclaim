from __future__ import annotations

from pathlib import Path

from app.settings import load_settings


def test_yaml_rules_load_and_environment_overrides(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "capture:\n  blur_min: 92\nreview:\n  row_count_disagreement_pct: 0.15\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HIRES_FPS", "3")

    settings = load_settings(settings_file, tmp_path / "missing.env")

    assert settings.config.capture.blur_min == 92
    assert settings.config.review.row_count_disagreement_pct == 0.15
    assert settings.hires_fps == 3
    assert settings.used_provider == "serpapi_ebay"
