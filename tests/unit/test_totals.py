from __future__ import annotations

from app.packet.models import (
    Book,
    FxInfo,
    Item,
    ItemReplacementCost,
    ReplacementCost,
    UsedValue,
)
from app.packet.totals import compute_totals


def _quote(amount: float | None, status: str = "priced") -> ReplacementCost:
    return ReplacementCost(
        amount=amount,
        source="Store" if amount is not None else "",
        url="https://store.example/item" if amount is not None else "",
        retrieved_at="2026-11-25T10:00:00Z" if amount is not None else "",
        converted=False,
        snapshot_path="evidence/prices/book_new.json" if amount is not None else None,
        price_status=status,
    )


def _used(amount: float | None, *, converted: bool = False, appraisal: bool = False) -> UsedValue:
    fx = (
        FxInfo(
            from_currency="GBP",
            to_currency="INR",
            rate=100.0,
            rate_date="2026-11-24",
            source="Frankfurter",
            url="https://api.frankfurter.dev/rates?from=GBP&to=INR",
        )
        if converted
        else None
    )
    return UsedValue(
        amount=amount,
        source="eBay UK" if amount is not None else "",
        url="https://ebay.co.uk/item/1" if amount is not None else "",
        retrieved_at="2026-11-25T10:00:00Z" if amount is not None else "",
        condition_assumed="Used – Good",
        converted=converted,
        fx=fx,
        snapshot_path="evidence/prices/book_used.json" if amount is not None else None,
        price_status="skipped_appraisal"
        if appraisal
        else ("priced" if amount is not None else "not_found"),
    )


def _book(
    book_id: str,
    *,
    status: str = "identified",
    replacement: float | None = None,
    used: float | None = None,
    converted: bool = False,
    excluded_reason: str | None = None,
) -> Book:
    appraisal = status == "needs_appraisal"
    return Book(
        id=book_id,
        shelf="A-1",
        position=1,
        frame_ref="frames/f_000001_0000001.jpg",
        status=status,
        title="Visible title" if status != "unidentified" else "",
        author="Visible author" if status != "unidentified" else "",
        edition="",
        isbn="",
        spine_height_cm=20.0,
        spine_thickness_cm=2.0,
        id_confidence=0.0 if status == "unidentified" else 0.8,
        replacement_cost=_quote(
            replacement,
            "skipped_appraisal"
            if appraisal
            else ("priced" if replacement is not None else "not_found"),
        ),
        used_value=_used(used, converted=converted, appraisal=appraisal),
        excluded_reason=excluded_reason,
    )


def _item(item_id: str, low: float | None, high: float | None, *, appraisal: bool = False) -> Item:
    return Item(
        id=item_id,
        category="lamp",
        description="Desk lamp",
        brand_model="",
        frame_ref="frames/f_000001_0000001.jpg",
        dimensions_cm={"w": 10.0, "h": 20.0, "d": 10.0},
        status="needs_appraisal" if appraisal else "range",
        replacement_cost=ItemReplacementCost(
            low=low,
            high=high,
            source="" if low is None else "Shopping results",
            url="" if low is None else "https://shop.example/search",
            retrieved_at="" if low is None else "2026-11-25T10:00:00Z",
            snapshot_path=None if low is None else f"evidence/prices/{item_id}.json",
        ),
        confidence=0.8,
    )


def test_totals_cover_null_appraisal_excluded_converted_and_ranges() -> None:
    books = [
        _book("b_0001", replacement=100.0, used=40.0),
        _book("b_0002", status="needs_appraisal"),
        _book("b_0003", replacement=50.0, used=20.0, converted=True),
        _book("b_0004", replacement=5.0, used=None, excluded_reason="not_mine"),
    ]
    items = [_item("i_001", 10.0, 30.0), _item("i_002", None, None, appraisal=True)]

    totals = compute_totals(books, items, "INR", shelf_run_m=1.25)

    assert totals.book_count == 3
    assert totals.books_identified == 2
    assert totals.books_needs_appraisal == 1
    assert totals.books_replacement_cost == 150.0
    assert totals.books_used_value == 60.0
    assert totals.books_priced_converted == 1
    assert totals.shelf_run_m == 1.25
    assert totals.sum_thickness_m == 0.06
    assert totals.items_replacement_cost_low == 10.0
    assert totals.items_replacement_cost_high == 30.0
    assert totals.items_needs_appraisal == 1
    assert totals.excluded_from_totals == 3
    assert set(totals.excluded_line_ids) == {"b_0002", "b_0004", "i_002"}


def test_null_prices_do_not_contribute_and_unknown_shelf_run_stays_null() -> None:
    totals = compute_totals([_book("b_0001")], [], "INR")

    assert totals.books_replacement_cost == 0.0
    assert totals.books_used_value == 0.0
    assert totals.shelf_run_m is None
    assert totals.excluded_from_totals == 1
