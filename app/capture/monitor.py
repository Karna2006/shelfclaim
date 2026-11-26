"""Create deterministic capture cues from rolling frame metrics.

Input: the latest frame records and configured thresholds. Output: one ranked
cue candidate with its measured window evidence, following architecture §4.3.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.pipeline.artifacts import FrameRecord
from app.settings import CaptureSettings, CueSettings


@dataclass(frozen=True)
class CueCandidate:
    kind: str
    text: str
    priority: int
    metrics: dict[str, float | int | None]


class CaptureMonitor:
    """Track a short frame window and enforce overall and per-cue rate limits."""

    _PRIORITY = {"TOO_FAST": 100, "LOW_LIGHT": 90, "BLURRY": 80, "GLARE": 70}

    def __init__(self, capture: CaptureSettings, cues: CueSettings) -> None:
        self.capture = capture
        self.cues = cues
        self.frames: deque[FrameRecord] = deque()
        self.last_sent_s = float("-inf")
        self.last_by_type: dict[str, float] = {}
        self.sustained_since_ms: dict[str, int] = {}

    def observe(self, frame: FrameRecord, *, user_speaking: bool = False) -> CueCandidate | None:
        self.frames.append(frame)
        cutoff = frame.t_ms - round(self.cues.window_s * 1000)
        while self.frames and self.frames[0].t_ms < cutoff:
            self.frames.popleft()
        candidate = self._candidate()
        if candidate is not None and candidate.kind in {"LOW_LIGHT", "BLURRY"}:
            other_kind = "BLURRY" if candidate.kind == "LOW_LIGHT" else "LOW_LIGHT"
            self.sustained_since_ms.pop(other_kind, None)
            started = self.sustained_since_ms.setdefault(candidate.kind, frame.t_ms)
            if frame.t_ms - started < self.cues.low_light_blurry_sustain_s * 1000:
                return None
        else:
            self.sustained_since_ms.clear()
        if candidate is None or user_speaking:
            return None
        now_s = frame.t_ms / 1000
        if now_s - self.last_sent_s < self.cues.min_gap_s:
            return None
        if now_s - self.last_by_type.get(candidate.kind, float("-inf")) < self.cues.same_type_gap_s:
            return None
        self.last_sent_s = now_s
        self.last_by_type[candidate.kind] = now_s
        return candidate

    def _candidate(self) -> CueCandidate | None:
        if not self.frames:
            return None
        count = len(self.frames)
        fast = [
            f
            for f in self.frames
            if f.gyro_dps is not None and f.gyro_dps > self.capture.speed_max_dps
        ]
        low = [f for f in self.frames if f.qc_verdict in {"low_light_blur", "dark"}]
        blurry = [f for f in self.frames if f.qc_verdict == "blurry"]
        glare = [
            f for f in self.frames if f.glare is not None and f.glare > self.capture.glare_max_frac
        ]
        metrics = {
            "window_frames": count,
            "fast_fraction": len(fast) / count,
            "low_light_fraction": len(low) / count,
            "blurry_fraction": len(blurry) / count,
            "glare_fraction": len(glare) / count,
            "median_blur": _median([f.blur for f in self.frames]),
            "median_exposure": _median([f.exposure for f in self.frames]),
            "median_gyro_dps": _median([f.gyro_dps for f in self.frames]),
        }
        rules = (
            (
                "TOO_FAST",
                len(fast) / count >= self.cues.blurred_fraction,
                "Move the phone more slowly.",
            ),
            (
                "LOW_LIGHT",
                len(low) / count >= self.cues.blurred_fraction,
                "It's dark, can you turn on a light?",
            ),
            (
                "BLURRY",
                len(blurry) / count >= self.cues.blurred_fraction,
                "Hold the phone steadier for a moment.",
            ),
            (
                "GLARE",
                len(glare) / count >= self.cues.blurred_fraction,
                "Tilt the phone slightly to reduce glare.",
            ),
        )
        for kind, matched, text in rules:
            if matched:
                return CueCandidate(kind, text, self._PRIORITY[kind], metrics)
        return None


def _median(values: list[float | None]) -> float | None:
    present = sorted(value for value in values if value is not None)
    if not present:
        return None
    middle = len(present) // 2
    if len(present) % 2:
        return float(present[middle])
    return float((present[middle - 1] + present[middle]) / 2)
