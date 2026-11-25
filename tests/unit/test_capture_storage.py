from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from app.capture.storage import CaptureMotion, FrameHeader, create_sweep, list_frames, save_frame
from app.settings import Settings


def _jpeg() -> bytes:
    image = np.zeros((240, 320), dtype=np.uint8)
    image[:, ::2] = 220
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def test_storage_writes_sweep_frame_and_jsonl_record(tmp_path: Path) -> None:
    settings = Settings(sweeps_dir=tmp_path, _env_file=None)
    sweep = create_sweep(tmp_path, "Test browser / 320x240", settings)
    header = FrameHeader(
        seq=1,
        t_ms=1200,
        w=320,
        h=240,
        motion=CaptureMotion(gyro_dps=12, gravity=(0, 0, 9.8)),
    )

    result = save_frame(tmp_path / sweep.id, header, _jpeg(), settings)
    frames = list_frames(tmp_path / sweep.id)

    assert (tmp_path / sweep.id / "sweep.json").is_file()
    assert (tmp_path / sweep.id / "frames/f_000001_0001200.jpg").is_file()
    assert result.record.path == "frames/f_000001_0001200.jpg"
    assert result.record.gravity == (0, 0, 9.8)
    assert len(frames) == 1 and frames[0].seq == 1
    assert result.qc_message()["type"] == "qc"


def test_storage_retry_does_not_append_duplicate_frame(tmp_path: Path) -> None:
    settings = Settings(sweeps_dir=tmp_path, _env_file=None)
    sweep = create_sweep(tmp_path, "Test browser / 320x240", settings)
    sweep_dir = tmp_path / sweep.id
    header = FrameHeader(seq=4, t_ms=300, w=320, h=240)

    save_frame(sweep_dir, header, _jpeg(), settings)
    repeated = save_frame(sweep_dir, header, _jpeg(), settings)

    assert repeated.record.seq == 4
    assert len(list_frames(sweep_dir)) == 1
