"""Pure packet totals from verified book and item lines.

Input: packet models and optional shelf-run measurement from S4. Output:
validated Totals with money rounded only at the serialization boundary.
Implements `docs/04_ARCHITECTURE.md` S10 step 3 and `docs/05_DATA_SCHEMA.md` §1.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.packet.models import Book, Item, Totals

_CENT = Decimal("0.01")


def _money(value: float | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _rounded(value: Decimal) -> float:
    return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _excluded_line_ids(books: Sequence[Book], items: Sequence[Item]) -> list[str]:
    """Return each line that is appraisal, excluded, or missing a required price."""
    excluded_ids = [
        book.id
        for book in books
        if book.excluded_reason is not None
        or book.status == "needs_appraisal"
        or book.replacement_cost.amount is None
        or book.used_value.amount is None
    ]
    excluded_ids.extend(
        item.id
        for item in items
        if item.excluded_reason is not None
        or item.status == "needs_appraisal"
        or item.replacement_cost.low is None
        or item.replacement_cost.high is None
    )
    return excluded_ids


def compute_totals(
    books: Sequence[Book],
    items: Sequence[Item],
    currency: str,
    *,
    shelf_run_m: float | None = None,
) -> Totals:
    """Compute claim totals; no text/model output participates in arithmetic."""
    owned_books = [book for book in books if book.excluded_reason is None]
    owned_items = [item for item in items if item.excluded_reason is None]

    replacement_total = sum(
        (_money(book.replacement_cost.amount) for book in owned_books), Decimal("0")
    )
    used_total = sum((_money(book.used_value.amount) for book in owned_books), Decimal("0"))
    item_low = sum((_money(item.replacement_cost.low) for item in owned_items), Decimal("0"))
    item_high = sum((_money(item.replacement_cost.high) for item in owned_items), Decimal("0"))

    excluded_ids = _excluded_line_ids(books, items)
    thickness_m = sum(
        (_money(book.spine_thickness_cm) / Decimal("100") for book in owned_books),
        Decimal("0"),
    )
    return Totals(
        book_count=len(owned_books),
        books_identified=sum(book.status == "identified" for book in owned_books),
        books_unidentified=sum(book.status == "unidentified" for book in owned_books),
        shelf_run_m=shelf_run_m,
        books_replacement_cost=_rounded(replacement_total),
        books_used_value=_rounded(used_total),
        items_replacement_cost_low=_rounded(item_low),
        items_replacement_cost_high=_rounded(item_high),
        excluded_from_totals=len(excluded_ids),
        books_needs_appraisal=sum(book.status == "needs_appraisal" for book in owned_books),
        items_needs_appraisal=sum(item.status == "needs_appraisal" for item in owned_items),
        excluded_line_ids=excluded_ids,
        books_priced_converted=sum(
            book.replacement_cost.converted or book.used_value.converted for book in owned_books
        ),
        sum_thickness_m=float(thickness_m) if owned_books else None,
        currency=currency,
    )
