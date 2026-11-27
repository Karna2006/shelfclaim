"""Select sharp images across equal sweep-time segments for vision calls.

Input: saved frame records and a frame budget. Output: one sharp frame per
coverage segment, preferring QC-ok frames, per docs/04 S0-S1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.capture.storage import list_frames
from app.pipeline.artifacts import FrameRecord


@dataclass(frozen=True)
class KeyframeChoice:
    segment: int
    frame: FrameRecord | None
    quality_fallback: bool


@dataclass(frozen=True)
class KeyframeSelection:
    choices: list[KeyframeChoice]

    @property
    def frames(self) -> list[FrameRecord]:
        return [choice.frame for choice in self.choices if choice.frame is not None]

    @property
    def review_choices(self) -> list[KeyframeChoice]:
        return [
            choice for choice in self.choices if choice.quality_fallback or choice.frame is None
        ]


def select_detection_keyframes(
    sweep_dir: Path,
    *,
    max_frames: int,
) -> KeyframeSelection:
    """Choose one sharpest QC-ok frame per time segment, with explicit fallbacks."""
    if not 1 <= max_frames <= 6:
        raise ValueError("detection keyframe budget must be between 1 and 6")
    records = sorted(list_frames(sweep_dir), key=lambda row: (row.t_ms, row.seq))
    return select_coverage_keyframes(records, segment_count=max_frames)


def select_coverage_keyframes(
    records: list[FrameRecord], *, segment_count: int
) -> KeyframeSelection:
    """Select the sharpest frame in each equal-duration segment."""
    if not 1 <= segment_count <= 6:
        raise ValueError("segment_count must be between 1 and 6")
    ordered = sorted(records, key=lambda row: (row.t_ms, row.seq))
    if not ordered:
        return KeyframeSelection(
            choices=[
                KeyframeChoice(segment=index, frame=None, quality_fallback=False)
                for index in range(segment_count)
            ]
        )
    buckets: dict[int, list[FrameRecord]] = {index: [] for index in range(segment_count)}
    origin_ms = ordered[0].t_ms
    duration_ms = ordered[-1].t_ms - origin_ms
    for record in ordered:
        if duration_ms <= 0:
            segment = 0
        else:
            position = (record.t_ms - origin_ms) / duration_ms
            segment = min(int(position * segment_count), segment_count - 1)
        buckets[segment].append(record)

    choices = []
    for segment, candidates in buckets.items():
        if not candidates:
            choices.append(KeyframeChoice(segment=segment, frame=None, quality_fallback=False))
            continue
        sharp_candidates = [row for row in candidates if row.qc_verdict == "ok"]
        quality_fallback = not sharp_candidates
        pool = sharp_candidates or candidates
        frame = max(pool, key=lambda row: (row.blur if row.blur is not None else -1, -row.seq))
        choices.append(
            KeyframeChoice(segment=segment, frame=frame, quality_fallback=quality_fallback)
        )
    return KeyframeSelection(choices=choices)


def describe_explicit_selection(
    records: list[FrameRecord], selected: list[FrameRecord], *, segment_count: int
) -> KeyframeSelection:
    """Annotate manual diagnostic frame choices with segment and QC status."""
    ordered = sorted(records, key=lambda row: (row.t_ms, row.seq))
    if not ordered:
        return KeyframeSelection(choices=[])
    origin_ms = ordered[0].t_ms
    duration_ms = ordered[-1].t_ms - origin_ms
    choices = []
    for frame in selected:
        if duration_ms <= 0:
            segment = 0
        else:
            position = (frame.t_ms - origin_ms) / duration_ms
            segment = min(int(position * segment_count), segment_count - 1)
        choices.append(
            KeyframeChoice(
                segment=segment,
                frame=frame,
                quality_fallback=frame.qc_verdict != "ok",
            )
        )
    return KeyframeSelection(choices=choices)
