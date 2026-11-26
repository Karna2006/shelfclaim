"""Filter real offer responses into robust deterministic book estimates.

Input: catalogue title, offer objects, and query metadata. Output: median of
physical offers passing title match; empty evidence remains an explicit null.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz

_EXCLUDED_TERMS = (
    "kindle",
    "ebook",
    "e-book",
    "audiobook",
    "audio book",
    "summary",
    "study guide",
    "workbook",
    "box set",
    "set of books",
    "poster",
)


@dataclass(frozen=True)
class PricedOffer:
    title: str
    amount: Decimal
    currency: str
    merchant: str
    url: str
    condition: str


@dataclass(frozen=True)
class Estimate:
    amount: Decimal | None
    offers: tuple[PricedOffer, ...]
    representative: PricedOffer | None


def parse_serp_offers(data: dict[str, Any], *, used: bool) -> list[PricedOffer]:
    """Normalize common Google Shopping and SerpAPI eBay offer records."""
    raw = data.get("organic_results", []) if used else data.get("shopping_results", [])
    offers = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        price = item.get("extracted_price")
        price_block = item.get("price")
        if price is None and isinstance(price_block, dict):
            price = price_block.get("extracted")
        if price is None and isinstance(price_block, str):
            price = _parse_price_text(price_block)
        try:
            amount = Decimal(str(price))
        except Exception:
            continue
        if not amount.is_finite() or amount <= 0:
            continue
        offers.append(
            PricedOffer(
                title=str(item.get("title", "")),
                amount=amount,
                currency=str(item.get("currency", "")),
                merchant=str(item.get("source", item.get("seller", ""))),
                url=str(item.get("link", "")),
                condition=str(item.get("condition", "used" if used else "new")),
            )
        )
    return offers


def estimate_book_price(
    title: str,
    offers: list[PricedOffer],
    *,
    used: bool,
    title_match_min: int = 80,
) -> Estimate:
    """Exclude weak, nonphysical, wrong-condition and IQR-outlier offers."""
    acceptable = [
        offer
        for offer in offers
        if offer.url
        and fuzz.token_set_ratio(title.casefold(), offer.title.casefold()) >= title_match_min
        and not any(term in offer.title.casefold() for term in _EXCLUDED_TERMS)
        and _condition_matches(offer.condition, used)
    ]
    if len(acceptable) >= 3:
        amounts = sorted(offer.amount for offer in acceptable)
        q1, q3 = _quartile(amounts, Decimal("0.25")), _quartile(amounts, Decimal("0.75"))
        spread = q3 - q1
        low, high = q1 - Decimal("1.5") * spread, q3 + Decimal("1.5") * spread
        acceptable = [offer for offer in acceptable if low <= offer.amount <= high]
    if not acceptable:
        return Estimate(None, (), None)
    ordered = sorted(acceptable, key=lambda offer: offer.amount)
    center = _median([offer.amount for offer in ordered])
    representative = min(ordered, key=lambda offer: abs(offer.amount - center))
    return Estimate(center, tuple(ordered), representative)


def _condition_matches(condition: str, used: bool) -> bool:
    normalized = condition.casefold()
    return (
        ("used" in normalized or "pre-owned" in normalized or "good" in normalized)
        if used
        else not any(word in normalized for word in ("used", "pre-owned", "refurbished"))
    )


def _parse_price_text(value: str) -> str | None:
    match = re.search(r"[\d,.]+", value)
    return match.group(0).replace(",", "") if match else None


def _quartile(values: list[Decimal], fraction: Decimal) -> Decimal:
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(len(values) - 1, low + 1)
    remainder = position - low
    return values[low] * (1 - remainder) + values[high] * remainder


def _median(values: list[Decimal]) -> Decimal:
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2
