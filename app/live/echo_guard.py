"""Suppress recent speaker echo before it reaches the agent model.

Input is recognized final text; output is a fuzzy match against recently
spoken agent and cue lines using the configured time and similarity limits.
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from rapidfuzz.fuzz import partial_ratio


@dataclass(frozen=True)
class EchoMatch:
    text: str
    similarity: float


@dataclass(frozen=True)
class CleanedTranscript:
    text: str
    removed_words: tuple[str, ...]
    matched_line: str | None = None


class EchoGuard:
    """Keep a short monotonic-time window of output lines to catch TTS echo."""

    def __init__(
        self,
        window_s: float = 6,
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
        """Match a full four-word transcript against recent spoken text."""
        words = _words(recognized_text)
        if len(words) < 4:
            return None
        now = self._clock()
        self._prune(now)
        best: EchoMatch | None = None
        for _, spoken in self._spoken:
            similarity = partial_ratio(" ".join(words), " ".join(_words(spoken)))
            if similarity >= self._match_ratio and (best is None or similarity > best.similarity):
                best = EchoMatch(spoken, similarity)
        return best

    def clean(self, recognized_text: str) -> CleanedTranscript:
        """Remove matching three-word TTS spans while preserving nearby user words."""
        now = self._clock()
        self._prune(now)
        raw_tokens = list(re.finditer(r"[a-z0-9']+", recognized_text, re.I))
        originals = [match.group(0) for match in raw_tokens]
        tokens = [word.casefold() for word in originals]
        if len(tokens) < 3 or not self._spoken:
            return CleanedTranscript(" ".join(originals), ())

        spoken_windows = [
            (line, window) for _, line in self._spoken for window in _windows(_words(line))
        ]
        removed: set[int] = set()
        matched_line: str | None = None
        for start, window in enumerate(_windows(tokens)):
            best_score = 0.0
            best_line = None
            for line, spoken_window in spoken_windows:
                score = partial_ratio(" ".join(window), " ".join(spoken_window))
                if score > best_score:
                    best_score, best_line = score, line
            if best_score >= self._match_ratio:
                removed.update(range(start, start + 3))
                matched_line = best_line
        cleaned = " ".join(token for index, token in enumerate(originals) if index not in removed)
        removed_words = tuple(token for index, token in enumerate(originals) if index in removed)
        return CleanedTranscript(cleaned, removed_words, matched_line)

    def _prune(self, now: float) -> None:
        while self._spoken and now - self._spoken[0][0] > self._window_s:
            self._spoken.popleft()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def _windows(words: list[str]) -> list[list[str]]:
    return [words[index : index + 3] for index in range(len(words) - 2)]
