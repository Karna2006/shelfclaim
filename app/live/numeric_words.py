"""Convert English numeric phrases into Decimal values for grounding checks.

Input: tokenized number words. Output: a normalized value and next token index.
Implements the numeric normalization policy for the live agent.
"""

from __future__ import annotations

from decimal import Decimal

SMALL = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
}
SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "billion": 1_000_000_000,
    "trillion": 1_000_000_000_000,
}
CURRENCIES_AND_UNITS = {
    "₹",
    "$",
    "£",
    "€",
    "%",
    "inr",
    "rupee",
    "rupees",
    "usd",
    "dollar",
    "dollars",
    "gbp",
    "pound",
    "pounds",
    "eur",
    "euro",
    "euros",
    "cm",
    "mm",
    "m",
    "m2",
    "sq",
    "metre",
    "metres",
    "meter",
    "meters",
    "inch",
    "inches",
    "foot",
    "feet",
    "percent",
    "percentage",
    "book",
    "books",
    "item",
    "items",
    "copy",
    "copies",
    "piece",
    "pieces",
    "frame",
    "frames",
    "marker",
    "markers",
    "row",
    "rows",
    "count",
    "counts",
    "total",
    "totals",
}
NUMBER_WORDS = set(SMALL) | set(TENS) | set(SCALES) | {"and", "point"}


def parse_number_words(words: list[str], start: int) -> tuple[Decimal, int] | None:
    """Parse a cardinal phrase such as twenty one lakh and five hundred."""
    total = Decimal(0)
    current = Decimal(0)
    saw_number = False
    index = start
    while index < len(words):
        word = words[index]
        if word in SMALL:
            current += SMALL[word]
            saw_number = True
        elif word in TENS:
            current += TENS[word]
            saw_number = True
        elif word == "hundred":
            current = max(current, Decimal(1)) * 100
            saw_number = True
        elif word in SCALES and word != "hundred":
            total += max(current, Decimal(1)) * SCALES[word]
            current = Decimal(0)
            saw_number = True
        elif word == "and" and saw_number and _at(words, index + 1) in NUMBER_WORDS:
            index += 1
            continue
        elif word == "point" and saw_number:
            fraction, end = _parse_spoken_decimal(words, index + 1)
            if fraction is None:
                break
            return total + current + fraction, end
        else:
            break
        index += 1
    if not saw_number:
        return None
    return total + current, index


def _parse_spoken_decimal(words: list[str], start: int) -> tuple[Decimal | None, int]:
    digits: list[str] = []
    index = start
    while index < len(words):
        word = words[index]
        if word not in SMALL or SMALL[word] > 9:
            break
        digits.append(str(SMALL[word]))
        index += 1
    if not digits:
        return None, start
    return Decimal(f"0.{''.join(digits)}"), index


def _at(words: list[str], index: int) -> str:
    return words[index] if index < len(words) else ""
