"""Price identified household items from physical offer evidence only.

Input: item category, visible brand/material and user statements. Output: an
exact-item range, a P25–P75 template range, or mandatory appraisal status.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.pricing.book_pricer import PricedOffer, _quartile
from rapidfuzz import fuzz


@dataclass(frozen=True)
class ItemEstimate:
    status: str
    low: Decimal | None
    high: Decimal | None
    offers: tuple[PricedOffer, ...]
    reason: str | None = None


def estimate_item_range(
    *,
    category: str,
    brand_model: str,
    material: str | None,
    offers: list[PricedOffer],
    is_artwork: bool = False,
    print_confirmed_by: str | None = None,
) -> ItemEstimate:
    """Require user confirmation for art and three physical offers for templates."""
    if is_artwork and not print_confirmed_by:
        return ItemEstimate("needs_appraisal", None, None, (), "artwork_not_confirmed_as_print")
    exact = bool(brand_model.strip())
    query_target = (
        brand_model if exact else " ".join(part for part in (category, material or "") if part)
    )
    matching = [
        offer
        for offer in offers
        if offer.url
        and offer.amount > 0
        and fuzz.token_set_ratio(query_target.casefold(), offer.title.casefold()) >= 80
        and not any(
            term in offer.title.casefold() for term in ("ebook", "audiobook", "digital download")
        )
    ]
    if exact:
        if not matching:
            return ItemEstimate("needs_appraisal", None, None, (), "brand_model_not_found")
        amounts = sorted(offer.amount for offer in matching)
        return ItemEstimate(
            "priced",
            _quartile(amounts, Decimal("0.25")),
            _quartile(amounts, Decimal("0.75")),
            tuple(matching),
        )
    if len(matching) < 3:
        return ItemEstimate(
            "needs_appraisal", None, None, tuple(matching), "fewer_than_three_template_offers"
        )
    amounts = sorted(offer.amount for offer in matching)
    return ItemEstimate(
        "range",
        _quartile(amounts, Decimal("0.25")),
        _quartile(amounts, Decimal("0.75")),
        tuple(matching),
    )
