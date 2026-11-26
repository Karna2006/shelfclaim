"""Suppress recent speaker echo before it reaches the agent model.

Input is recognized final text; output is a fuzzy match against recently
spoken agent and cue lines using the configured time and similarity limits.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from rapidfuzz.fuzz import ratio


@dataclass(frozen=True)
class EchoMatch:
    text: str
    similarity: float


class EchoGuard:
    """Keep a short monotonic-time window of output lines to catch TTS echo."""

    def __init__(
        self,
        window_s: float = 10,
        match_ratio: int = 85,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window_s = window_s
        self._match_ratio = match_ratio
        self._clock = clock
        self._spoken: deque[tuple[float, str]] = deque()

    def add_spoken_line(self, text: str) -> None:
        cleaned = text.strip()
        if cleaned:
            self._prune(self._clock())
            self._spoken.append((self._clock(), cleaned))

    def match(self, recognized_text: str) -> EchoMatch | None:
        """Return the strongest recent line matching the configured ratio."""
        now = self._clock()
        self._prune(now)
        best: EchoMatch | None = None
        for _, spoken in self._spoken:
            similarity = ratio(recognized_text.strip(), spoken)
            if similarity >= self._match_ratio and (best is None or similarity > best.similarity):
                best = EchoMatch(spoken, similarity)
        return best

    def _prune(self, now: float) -> None:
        while self._spoken and now - self._spoken[0][0] > self._window_s:
            self._spoken.popleft()
