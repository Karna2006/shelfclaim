from __future__ import annotations

from pathlib import Path

import pytest
from app.cli import generate_marker_pdf


def test_marker_pdf_has_one_a4_page_per_id(tmp_path: Path) -> None:
    output = generate_marker_pdf((0, 1, 2), 100.0, tmp_path / "cards.pdf")
    content = output.read_bytes()

    assert content.startswith(b"%PDF-")
    assert content.count(b"/MediaBox") == 3


def test_marker_generator_rejects_unknown_dictionary_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 0 and 49"):
        generate_marker_pdf((50, 1, 2), 100.0, tmp_path / "cards.pdf")
