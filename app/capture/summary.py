"""Summarize capture quality from the saved frame manifest.

Input is validated `FrameRecord` data and capture settings; output is a small
summary for `inspect-sweep`. Implements capture inspection in `docs/06_USER_FLOWS.md` §6.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.capture.quality import Verdict, classify_verdict
from app.pipeline.artifacts import FrameRecord
from app.settings import CaptureSettings

_CATEGORIES = ("ok", "blurry", "fast", "glare", "dark", "bright")


@dataclass(frozen=True)
class SweepCaptureSummary:
    frame_count: int
    duration_s: float
    fps: float
    percentages: dict[str, float]
    markers_seen: tuple[int, ...]


def summarize_frames(records: list[FrameRecord], settings: CaptureSettings) -> SweepCaptureSummary:
    """Aggregate exclusive QC percentages, elapsed capture time, and marker IDs."""
    if not records:
        return SweepCaptureSummary(0, 0.0, 0.0, {category: 0.0 for category in _CATEGORIES}, ())

    timestamps = [record.t_ms for record in records]
    duration_s = (max(timestamps) - min(timestamps)) / 1000
    fps = (len(records) - 1) / duration_s if duration_s > 0 and len(records) > 1 else 0.0
    counts = {category: 0 for category in _CATEGORIES}
    markers = {marker.id for record in records for marker in record.markers}
    legacy_fast = _legacy_fast_flags(records, settings)

    for record in records:
        verdict = _record_verdict(record, settings, legacy_fast[record.seq])
        category = "dark" if verdict in ("dark", "low_light_blur") else verdict
        counts[category] += 1

    percentages = {category: counts[category] * 100 / len(records) for category in _CATEGORIES}
    return SweepCaptureSummary(len(records), duration_s, fps, percentages, tuple(sorted(markers)))


def _record_verdict(
    record: FrameRecord, settings: CaptureSettings, fast_sustained: bool
) -> Verdict:
    if record.qc_verdict is not None:
        return record.qc_verdict
    # Older manifests lack a verdict; classify from saved metrics and sampled gyro windows.
    return classify_verdict(
        record.blur,
        record.glare,
        record.exposure,
        record.gyro_dps,
        settings,
        fast_sustained=fast_sustained,
    )


def _legacy_fast_flags(records: list[FrameRecord], settings: CaptureSettings) -> dict[int, bool]:
    """Approximate sustained fast motion from frame gyro samples in old manifests."""
    started_at_ms: int | None = None
    fast_flags: dict[int, bool] = {}
    for record in sorted(records, key=lambda frame: frame.t_ms):
        if record.gyro_dps is None or record.gyro_dps <= settings.speed_max_dps:
            started_at_ms = None
            fast_flags[record.seq] = False
            continue
        if started_at_ms is None:
            started_at_ms = record.t_ms
        fast_flags[record.seq] = record.t_ms - started_at_ms >= settings.speed_sustain_s * 1000
    return fast_flags
