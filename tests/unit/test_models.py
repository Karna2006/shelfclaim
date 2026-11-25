from __future__ import annotations

import pytest
from app.packet.models import (
    Book,
    Item,
    ItemReplacementCost,
    ReplacementCost,
    Room,
    ScaleAnchor,
    UsedValue,
)
from pydantic import ValidationError


def _replacement(amount: float | None = None, **overrides: object) -> ReplacementCost:
    values: dict[str, object] = {
        "amount": amount,
        "source": "",
        "url": "",
        "retrieved_at": "",
        "converted": False,
        "snapshot_path": None,
        "price_status": "priced" if amount is not None else "not_found",
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
        "price_status": "priced" if amount is not None else "not_found",
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
        "catalogue_ref": None
        if overrides.get("status") == "unidentified"
        else "openlibrary:/works/OL1W",
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


def test_price_status_matches_positive_amount_presence() -> None:
    with pytest.raises(ValidationError, match="priced status must match"):
        _replacement(None, price_status="priced")
    with pytest.raises(ValidationError, match="priced status must match"):
        _used(
            12.0,
            source="Shop",
            url="https://shop.example/item",
            retrieved_at="2026-11-25T10:00:00Z",
            snapshot_path="evidence/prices/b_0001_used.json",
            price_status="not_found",
        )
    with pytest.raises(ValidationError, match="greater than 0"):
        _replacement(
            0.0,
            source="Shop",
            url="https://shop.example/item",
            retrieved_at="2026-11-25T10:00:00Z",
            snapshot_path="evidence/prices/b_0001_new.json",
            price_status="priced",
        )


def test_unidentified_book_cannot_have_a_title() -> None:
    with pytest.raises(ValidationError, match="unidentified books"):
        _book(status="unidentified")


def test_identified_book_requires_catalogue_match_reference() -> None:
    with pytest.raises(ValidationError, match="catalogue match reference"):
        _book(catalogue_ref=None)
    with pytest.raises(ValidationError, match="catalogue match reference"):
        _book(catalogue_ref=" ")


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


def test_item_status_and_range_validators_reject_invalid_prices() -> None:
    evidence = {
        "source": "Shop",
        "url": "https://shop.example/item",
        "retrieved_at": "2026-11-25T10:00:00Z",
        "snapshot_path": "evidence/prices/item.json",
    }
    with pytest.raises(ValidationError, match="low must be less than or equal to high"):
        ItemReplacementCost(low=12.0, high=10.0, **evidence)
    with pytest.raises(ValidationError, match="greater than 0"):
        ItemReplacementCost(low=0.0, high=10.0, **evidence)

    item_values = {
        "id": "i_001",
        "category": "lamp",
        "description": "Desk lamp",
        "brand_model": "",
        "frame_ref": "frames/f_000001_0000001.jpg",
        "dimensions_cm": {},
        "replacement_cost": ItemReplacementCost(
            low=None, high=None, source="", url="", retrieved_at=""
        ),
        "confidence": 0.8,
    }
    for status in ("priced", "range"):
        with pytest.raises(ValidationError, match="require both price bounds"):
            Item.model_validate({**item_values, "status": status})
    with pytest.raises(ValidationError, match="cannot carry prices"):
        Item.model_validate(
            {
                **item_values,
                "status": "needs_appraisal",
                "replacement_cost": ItemReplacementCost(low=10, high=12, **evidence),
            }
        )


def test_room_measurements_reject_zero_values() -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        Room(
            length_m=None,
            width_m=None,
            height_m=None,
            floor_area_m2=0,
            wall_area_m2=None,
            shelved_wall_area_m2=None,
            scale_method="none",
            confidence=0,
        )


def test_scale_anchor_rejects_zero_factor() -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        ScaleAnchor(
            kind="aruco",
            detail="marker scale",
            scale_factor=0,
            weight=1,
        )


def test_artwork_requires_a_print_confirming_user_statement_when_priced() -> None:
    priced_art = {
        "id": "i_art",
        "category": "framed_art",
        "description": "Framed landscape print",
        "brand_model": "",
        "frame_ref": "frames/f_000001_0000001.jpg",
        "dimensions_cm": {},
        "status": "range",
        "replacement_cost": ItemReplacementCost(
            low=20,
            high=30,
            source="Shop",
            url="https://shop.example/prints",
            retrieved_at="2026-11-25T10:00:00Z",
            snapshot_path="evidence/prices/i_art.json",
        ),
        "confidence": 0.8,
        "is_artwork": True,
    }
    with pytest.raises(ValidationError, match="print-confirming user statement"):
        Item.model_validate(priced_art)

    print_confirmed = Item.model_validate(
        {**priced_art, "print_confirmed_by": "us_004", "user_statements": ["us_004"]}
    )
    assert print_confirmed.print_confirmed_by == "us_004"

    appraisal_art = Item.model_validate(
        {
            **priced_art,
            "status": "needs_appraisal",
            "replacement_cost": ItemReplacementCost(
                low=None, high=None, source="", url="", retrieved_at=""
            ),
        }
    )
    assert appraisal_art.print_confirmed_by is None
