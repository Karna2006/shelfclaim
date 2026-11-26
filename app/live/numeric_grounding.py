"""Match reply number claims against recent deterministic tool results.

Input: extracted claims and the last ten structured tool results. Output:
claims that are not exact matches or permitted approximate roundings.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.live.numeric_words import CURRENCIES_AND_UNITS, ORDINALS, parse_number_words

_TOKEN_RE = re.compile(r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|[A-Za-z]+|[₹$£€%]")


@dataclass(frozen=True)
class NumericClaim:
    """A numeric phrase, its normalized decimal value, and approximation marker."""

    token: str
    value: Decimal
    approximate: bool


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int


def find_ungrounded_claims(
    text: str, recent_tool_results: list[object] | tuple[object, ...]
) -> list[NumericClaim]:
    """Return claims unmatched by any value in the supplied tool results."""
    allowed_values = list(_tool_values(recent_tool_results))
    return [
        claim
        for claim in extract_numeric_claims(text)
        if not any(_matches(claim, value) for value in allowed_values)
    ]


def extract_numeric_claims(text: str) -> list[NumericClaim]:
    """Extract digit and English number-word phrases from free text."""
    tokens = [
        _Token(match.group(), match.start(), match.end()) for match in _TOKEN_RE.finditer(text)
    ]
    words = [token.text.casefold() for token in tokens]
    claims: list[NumericClaim] = []
    index = 0
    while index < len(tokens):
        word = words[index]
        if _is_digit_token(tokens[index].text):
            value = Decimal(tokens[index].text.replace(",", ""))
            start, end = _include_currency(tokens, index)
            claims.append(_claim(text, tokens, start, end, value))
            index += 1
            continue
        if word in ORDINALS:
            if _word_at(words, index + 1) in CURRENCIES_AND_UNITS:
                claims.append(_claim(text, tokens, index, index + 1, Decimal(ORDINALS[word])))
            index += 1
            continue
        if word == "one" and _word_at(words, index + 1) in {"more", "moment"}:
            index += 1
            continue
        parsed = parse_number_words(words, index)
        if parsed is None:
            index += 1
            continue
        value, end_index = parsed
        claims.append(_claim(text, tokens, index, end_index, value))
        index = end_index
    return claims


def _claim(text: str, tokens: list[_Token], start: int, end: int, value: Decimal) -> NumericClaim:
    prefix = text[max(0, tokens[start].start - 12) : tokens[start].start]
    approximate = bool(re.search(r"\b(?:about|around)\s*$", prefix, re.IGNORECASE))
    return NumericClaim(
        token=text[tokens[start].start : tokens[end - 1].end],
        value=value,
        approximate=approximate,
    )


def _tool_values(results: list[object] | tuple[object, ...]) -> Iterator[Decimal]:
    for result in results:
        yield from _values_in(result)


def _values_in(value: object) -> Iterator[Decimal]:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return
        if number.is_finite():
            yield number
        return
    if isinstance(value, str):
        for claim in extract_numeric_claims(value):
            yield claim.value
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _values_in(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            yield from _values_in(nested)


def _matches(claim: NumericClaim, allowed: Decimal) -> bool:
    if claim.value == allowed:
        return True
    if not claim.approximate:
        return False
    for exponent in (0, -1, 2, 3):
        quantum = Decimal(1).scaleb(exponent)
        if claim.value == allowed.quantize(quantum, rounding=ROUND_HALF_UP):
            return True
    return False


def _include_currency(tokens: list[_Token], index: int) -> tuple[int, int]:
    start = index
    if index > 0 and tokens[index - 1].text in {"₹", "$", "£", "€"}:
        start -= 1
    end = index + 1
    if _word_at([token.text for token in tokens], end) == "%":
        end += 1
    return start, end


def _is_digit_token(token: str) -> bool:
    return bool(token and token[0].isascii() and token[0].isdigit())


def _word_at(words: list[str], index: int) -> str:
    return words[index] if index < len(words) else ""
