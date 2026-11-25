from __future__ import annotations

import numpy as np
from app.capture.faces import blur_faces


def test_haar_face_blur_runs_without_error_on_empty_scene() -> None:
    image = np.zeros((240, 320, 3), dtype=np.uint8)

    redacted, face_count = blur_faces(image)

    assert redacted.shape == image.shape
    assert face_count >= 0
