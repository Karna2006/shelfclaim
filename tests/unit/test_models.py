from __future__ import annotations

import pytest
from app.packet.models import Book, ItemReplacementCost, ReplacementCost, UsedValue
from pydantic import ValidationError


def _replacement(amount: float | None = None, **overrides: object) -> ReplacementCost:
    values: dict[str, object] = {
        "amount": amount,
        "source": "",
        "url": "",
        "retrieved_at": "",
        "converted": False,
        "snapshot_path": None,
        "price_status": "not_found",
    }
    values.update(overrides)
    return ReplacementCost.model_validate(values)


def _used(amount: float | None = None, **overrides: object) -> UsedValue:
    values: dict[str, object] = {
        "amount": amount,
        "source": "",
        "url": "",
        "retrieved_at": "",
        "condition_assumed": "Used – Good",
        "converted": False,
        "snapshot_path": None,
        "price_status": "not_found",
    }
    values.update(overrides)
    return UsedValue.model_validate(values)


def _book(**overrides: object) -> Book:
    values: dict[str, object] = {
        "id": "b_0001",
        "shelf": "A-1",
        "position": 1,
        "frame_ref": "frames/f_000001_0000001.jpg",
        "status": "identified",
        "title": "A visible title",
        "author": "An Author",
        "edition": "",
        "isbn": "",
        "spine_height_cm": 20.0,
        "spine_thickness_cm": 2.0,
        "id_confidence": 0.9,
        "replacement_cost": _replacement(),
        "used_value": _used(),
    }
    values.update(overrides)
    return Book.model_validate(values)


def test_price_amount_requires_url_and_snapshot() -> None:
    with pytest.raises(ValidationError, match="url, retrieved_at and snapshot_path"):
        _replacement(
            12.0,
            source="Shop",
            retrieved_at="2026-11-25T10:00:00Z",
            snapshot_path=None,
        )


def test_price_amount_requires_source() -> None:
    with pytest.raises(ValidationError, match="requires source, url"):
        _replacement(
            12.0,
            source=" ",
            url="https://shop.example/item",
            retrieved_at="2026-11-25T10:00:00Z",
            snapshot_path="evidence/prices/b_0001_new.json",
            price_status="priced",
        )


def test_used_amount_requires_source() -> None:
    with pytest.raises(ValidationError, match="requires source, url"):
        _used(
            12.0,
            source="",
            url="https://shop.example/item",
            retrieved_at="2026-11-25T10:00:00Z",
            snapshot_path="evidence/prices/b_0001_used.json",
            price_status="priced",
        )


def test_item_price_requires_source() -> None:
    with pytest.raises(ValidationError, match="require source, url"):
        ItemReplacementCost(
            low=10.0,
            high=12.0,
            source="",
            url="https://shop.example/item",
            retrieved_at="2026-11-25T10:00:00Z",
            snapshot_path="evidence/prices/i_001.json",
        )


def test_converted_price_requires_fx() -> None:
    with pytest.raises(ValidationError, match="FX evidence"):
        _replacement(
            12.0,
            source="Shop",
            url="https://shop.example/item",
            retrieved_at="2026-11-25T10:00:00Z",
            snapshot_path="evidence/prices/b_0001_new.json",
            converted=True,
        )


def test_unidentified_book_cannot_have_a_title() -> None:
    with pytest.raises(ValidationError, match="unidentified books"):
        _book(status="unidentified")


def test_appraisal_book_cannot_have_an_amount() -> None:
    priced_replacement = _replacement(
        99.0,
        source="Shop",
        url="https://shop.example/item",
        retrieved_at="2026-11-25T10:00:00Z",
        snapshot_path="evidence/prices/b_0001_new.json",
        price_status="priced",
    )
    with pytest.raises(ValidationError, match="cannot carry prices"):
        _book(
            status="needs_appraisal",
            replacement_cost=priced_replacement,
            used_value=_used(),
        )
