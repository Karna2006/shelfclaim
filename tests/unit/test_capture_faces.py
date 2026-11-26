from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from app.capture.faces import YuNetDetectorCache, blur_faces
from app.settings import CaptureSettings


def test_empty_scene_has_no_face_detections(tmp_path: Path) -> None:
    image = np.zeros((240, 320, 3), dtype=np.uint8)

    redacted, face_boxes = blur_faces(image, model_path=tmp_path / "missing.onnx")

    assert redacted.shape == image.shape
    assert face_boxes == []


def test_bookshelf_stripes_and_spine_text_are_not_faces(tmp_path: Path) -> None:
    image = np.full((480, 640, 3), 225, dtype=np.uint8)
    spine_colors = [
        (45, 70, 140),
        (130, 70, 45),
        (70, 120, 75),
        (115, 60, 125),
        (45, 110, 145),
        (145, 105, 40),
        (55, 85, 125),
        (120, 75, 60),
    ]
    for index, color in enumerate(spine_colors):
        left = 24 + index * 72
        cv2.rectangle(image, (left, 35), (left + 62, 445), color, thickness=-1)
        cv2.line(image, (left + 8, 42), (left + 8, 438), (235, 225, 190), thickness=2)
        for text_y in (120, 170, 220, 310, 360):
            cv2.putText(
                image,
                "BOOK",
                (left + 14, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.28,
                (240, 235, 210),
                1,
                cv2.LINE_AA,
            )
    cv2.rectangle(image, (15, 450), (625, 470), (95, 65, 35), thickness=-1)

    _, face_boxes = blur_faces(image)

    assert face_boxes == []


def test_missing_model_uses_strict_haar_parameters(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    class FakeCascade:
        def empty(self) -> bool:
            return False

        def detectMultiScale(self, image, **kwargs):
            observed.update(kwargs)
            return np.array([[12, 15, 40, 45]])

    monkeypatch.setattr(cv2, "CascadeClassifier", lambda _: FakeCascade())
    settings = CaptureSettings(haar_min_neighbors=9, haar_min_size_fraction=0.10)
    image = np.zeros((200, 320, 3), dtype=np.uint8)

    _, face_boxes = blur_faces(image, settings, tmp_path / "missing.onnx")

    assert observed["minNeighbors"] == 9
    assert observed["minSize"] == (20, 20)
    assert face_boxes == [(12, 15, 40, 45, None)]


def test_yunet_uses_configured_threshold_and_records_score(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "yunet.onnx"
    model_path.touch()
    observed: dict[str, object] = {}

    class FakeDetector:
        def detect(self, frame):
            rows = np.zeros((1, 15), dtype=np.float32)
            rows[0, :5] = (10, 20, 30, 40, 0)
            rows[0, 14] = 0.93
            return 1, rows

    def create_detector(model, config, size, score, nms, top_k):
        observed.update(model=model, size=size, score=score)
        return FakeDetector()

    monkeypatch.setattr(cv2.FaceDetectorYN, "create", create_detector)
    image = np.zeros((80, 100, 3), dtype=np.uint8)
    settings = CaptureSettings(face_score_threshold=0.87)

    _, face_boxes = blur_faces(image, settings, model_path)

    assert observed["size"] == (100, 80)
    assert observed["score"] == 0.87
    assert face_boxes[0][:4] == (10, 20, 30, 40)
    assert np.isclose(face_boxes[0][4], 0.93)


def test_yunet_detector_is_constructed_once_and_resizes_only_on_change(
    monkeypatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "yunet.onnx"
    model_path.touch()
    observed = {"created": 0, "detects": 0, "resizes": 0}

    class FakeDetector:
        def setInputSize(self, size):
            observed["resizes"] += 1

        def detect(self, frame):
            observed["detects"] += 1
            return 1, None

    def create_detector(*_args):
        observed["created"] += 1
        return FakeDetector()

    monkeypatch.setattr(cv2.FaceDetectorYN, "create", create_detector)
    cache = YuNetDetectorCache()
    for size in ((80, 100), (80, 100), (80, 100), (60, 90), (60, 90)):
        image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        _, boxes = blur_faces(image, model_path=model_path, detector_cache=cache)
        assert boxes == []

    assert observed == {"created": 1, "detects": 5, "resizes": 1}
