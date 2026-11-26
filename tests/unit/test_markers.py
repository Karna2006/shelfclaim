from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from app.capture.marker_pdf import generate_marker_pdf
from app.capture.markers import detect_markers
from app.settings import Settings


def test_marker_pdf_has_one_a4_page_per_id(tmp_path: Path) -> None:
    output = generate_marker_pdf((0, 1, 2), 100.0, tmp_path / "cards.pdf")
    content = output.read_bytes()

    assert content.startswith(b"%PDF-")
    assert content.count(b"/MediaBox") == 3


def test_marker_generator_rejects_unknown_dictionary_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 0 and 49"):
        generate_marker_pdf((50, 1, 2), 100.0, tmp_path / "cards.pdf")


def test_marker_detector_finds_generated_marker() -> None:
    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    marker = aruco.generateImageMarker(dictionary, 7, 200)
    image = np.full((300, 300), 255, dtype=np.uint8)
    image[50:250, 50:250] = marker
    frame = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    found = detect_markers(frame, Settings(_env_file=None))

    assert [marker.id for marker in found] == [7]
    assert len(found[0].corners) == 4
