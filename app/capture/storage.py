"""Create sweeps and persist face-redacted frame evidence.

Inputs are client device metadata and binary JPEG/header pairs; outputs are
validated sweep metadata, JPEG files, and `frames.jsonl` records per schema §2.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml
from app.capture.faces import blur_faces
from app.capture.markers import detect_markers
from app.capture.quality import QualityScores, Verdict, classify_verdict, score_frame
from app.packet.models import Sweep
from app.pipeline.artifacts import FrameRecord, MarkerObservation
from app.settings import Settings
from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class CaptureResult:
    record: FrameRecord
    quality: QualityScores

    def qc_message(self) -> dict[str, object]:
        return {
            "type": "qc",
            "seq": self.record.seq,
            "blur": self.record.blur,
            "glare": self.record.glare,
            "exposure": self.record.exposure,
            "speed_dps": self.record.gyro_dps,
            "verdict": self.quality.verdict,
            "markers": [marker.id for marker in self.record.markers],
        }


class CaptureMotion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gyro_dps: float | None = Field(default=None, ge=0)
    gravity: tuple[float, float, float] | None = None
    alpha: float | None = None
    beta: float | None = None
    gamma: float | None = None


class FrameHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0)
    t_ms: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    motion: CaptureMotion | None = None


def create_sweep(sweeps_dir: Path, device: str, settings: Settings) -> Sweep:
    """Create a schema-valid sweep folder and its initial metadata file."""
    if not device.strip():
        raise ValueError("device metadata cannot be empty")
    if len(device) > 512:
        raise ValueError("device metadata is too long")

    captured_at = datetime.now().astimezone()
    country = settings.default_country.upper()
    locale_path = Path(__file__).resolve().parents[2] / "config" / "locales" / f"{country}.yaml"
    locale = yaml.safe_load(locale_path.read_text(encoding="utf-8"))
    sweep_id = f"sw_{captured_at:%Y%m%d_%H%M%S}_{secrets.token_hex(2)}"
    sweep_dir = sweeps_dir / sweep_id
    sweep_dir.mkdir(parents=True, exist_ok=False)
    (sweep_dir / "frames").mkdir()
    sweep = Sweep(
        id=sweep_id,
        captured_at=captured_at.isoformat(),
        device=device,
        duration_s=0,
        country=locale["country"],
        currency=locale["currency"],
        locale_config=f"config/locales/{country}.yaml",
    )
    (sweep_dir / "sweep.json").write_text(sweep.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return sweep


def save_frame(
    sweep_dir: Path,
    header: FrameHeader,
    jpeg_bytes: bytes,
    settings: Settings,
    fast_sustained: bool = False,
) -> CaptureResult:
    """Score, redact, and persist one frame, reusing an acknowledged sequence on retry."""
    seq = header.seq
    relative_path = f"frames/f_{seq:06d}_{header.t_ms:07d}.jpg"
    frame_path = sweep_dir / relative_path
    if frame_path.exists():
        previous = _find_record(sweep_dir / "frames.jsonl", seq)
        if previous is not None:
            return _retry_result(previous, settings, fast_sustained)

    image = _decode_jpeg(jpeg_bytes, header)
    height, width = image.shape[:2]

    gyro_dps = header.motion.gyro_dps if header.motion is not None else None
    quality = score_frame(image, settings.config.capture, gyro_dps, fast_sustained)
    markers, face_boxes, jpeg_to_save = _redact_and_encode(image, jpeg_bytes, settings)
    frame_path.write_bytes(jpeg_to_save)
    record = FrameRecord(
        seq=seq,
        t_ms=header.t_ms,
        path=relative_path,
        w=width,
        h=height,
        blur=quality.blur,
        glare=quality.glare,
        exposure=quality.exposure,
        gyro_dps=gyro_dps,
        qc_verdict=quality.verdict,
        gravity=header.motion.gravity if header.motion is not None else None,
        markers=markers,
        face_boxes=face_boxes,
        faces_blurred=len(face_boxes),
    )
    _append_record(sweep_dir / "frames.jsonl", record)
    return CaptureResult(record, quality)


def list_frames(sweep_dir: Path) -> list[FrameRecord]:
    """Load and validate frame rows for the developer's sweep inspection command."""
    manifest = sweep_dir / "frames.jsonl"
    if not manifest.exists():
        return []
    return [
        FrameRecord.model_validate_json(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _find_record(manifest: Path, seq: int) -> FrameRecord | None:
    if not manifest.exists():
        return None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = FrameRecord.model_validate_json(line)
        if record.seq == seq:
            return record
    return None


def _decode_jpeg(jpeg_bytes: bytes, header: FrameHeader) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("frame payload is not a decodable JPEG")
    if (image.shape[1], image.shape[0]) != (header.w, header.h):
        raise ValueError("frame dimensions do not match the packet header")
    return image


def _redact_and_encode(
    frame: np.ndarray, jpeg_bytes: bytes, settings: Settings
) -> tuple[list[MarkerObservation], list[tuple[int, int, int, int, float | None]], bytes]:
    markers = detect_markers(frame, settings)
    redacted, face_boxes = blur_faces(frame, settings.config.capture)
    if not face_boxes:
        return markers, face_boxes, jpeg_bytes

    encoded_ok, encoded = cv2.imencode(
        ".jpg",
        redacted,
        [cv2.IMWRITE_JPEG_QUALITY, round(settings.config.capture.jpeg_quality * 100)],
    )
    if not encoded_ok:
        raise RuntimeError("could not encode the redacted frame")
    return markers, face_boxes, encoded.tobytes()


def _append_record(manifest: Path, record: FrameRecord) -> None:
    with manifest.open("a", encoding="utf-8", newline="\n") as records:
        records.write(record.model_dump_json() + "\n")


def _retry_result(record: FrameRecord, settings: Settings, fast_sustained: bool) -> CaptureResult:
    # Reusing saved metrics prevents a lost WebSocket ack from creating duplicate evidence.
    quality = QualityScores(
        blur=record.blur,
        glare=record.glare,
        exposure=record.exposure,
        speed_dps=record.gyro_dps,
        verdict=_verdict_from_record(record, settings, fast_sustained),
    )
    return CaptureResult(record, quality)


def _verdict_from_record(record: FrameRecord, settings: Settings, fast_sustained: bool) -> Verdict:
    capture = settings.config.capture
    return classify_verdict(
        record.blur,
        record.glare,
        record.exposure,
        record.gyro_dps,
        capture,
        fast_sustained=fast_sustained,
    )
