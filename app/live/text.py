"""Normalize scripted live replies and lightweight utterance routing.

Input: final user text or model output. Output: a configured locale, a reviewed
scripted response, bounded response text, or a frame marker.
"""

from __future__ import annotations

import re

from app.prompts.loader import ScriptedLines


def question_script(text: str, lines: ScriptedLines) -> str | None:
    """Answer common title and price questions with reviewed wording."""
    normalized = text.casefold()
    if any(word in normalized for word in ("price", "cost", "worth", "how much")):
        return lines.price_question
    title_phrases = ("which book", "what book", "title", "identify this book")
    if any(word in normalized for word in title_phrases):
        return lines.title_question
    return None


def deterministic_locale(text: str) -> tuple[str, str] | None:
    """Resolve a clear opening confirmation without spending a model turn."""
    tokens = re.findall(r"[a-z]+", text.casefold())
    india = any(token in {"india", "rupees", "inr"} for token in tokens)
    uk = any(token in {"uk", "pounds", "gbp"} for token in tokens)
    if india and uk:
        return None
    if india:
        return "IN", "INR"
    if uk:
        return "GB", "GBP"
    affirmations = {"yes", "yeah", "yep", "correct", "haan", "ha", "sure"}
    if tokens and tokens[0] in affirmations:
        return "IN", "INR"
    if tokens in (["right"], ["right", "yes"], ["that", "is", "right"]):
        return "IN", "INR"
    return None


def limit_reply(text: str) -> tuple[str, bool]:
    """Keep replies within two complete sentences and thirty whitespace words."""
    normalized = text.strip()
    sentences = [
        match.group(0).strip()
        for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", normalized)
        if match.group(0).strip()
    ]
    selected: list[str] = []
    for sentence in sentences[:2]:
        candidate = " ".join([*selected, sentence])
        if len(candidate.split()) > 30:
            break
        selected.append(sentence)
    limited = " ".join(selected) if selected else "Sorry, say that again?"
    return limited, limited != normalized


def frame_marker(sequence: int | None) -> str:
    return f"[frame f_{sequence:06d}]" if sequence is not None else "[frame f_latest]"
