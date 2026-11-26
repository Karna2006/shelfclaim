from __future__ import annotations

from app.packet.models import (
    Book,
    ClaimPacket,
    ReplacementCost,
    Room,
    Sweep,
    UsedValue,
)
from app.packet.report import render_report
from app.packet.totals import compute_totals


def test_report_links_book_frame_and_both_price_sources() -> None:
    sweep = Sweep(
        id="sw_report",
        captured_at="2026-11-26T00:00:00Z",
        device="fixture",
        duration_s=1,
        country="IN",
        currency="INR",
    )
    book = Book(
        id="b_0001",
        shelf="A-1",
        position=1,
        frame_ref="frames/book.jpg",
        status="identified",
        title="Example Book",
        author="A. Writer",
        edition="",
        isbn="",
        id_confidence=0.9,
        replacement_cost=ReplacementCost(
            amount=500,
            source="Book Shop",
            url="https://shop.example/book",
            retrieved_at="2026-11-26T00:00:00Z",
            currency="INR",
            snapshot_path="evidence/prices/new.json",
        ),
        used_value=UsedValue(
            amount=300,
            source="eBay",
            url="https://ebay.example/item",
            retrieved_at="2026-11-26T00:00:00Z",
            condition_assumed="Used – Good",
            currency="INR",
            snapshot_path="evidence/prices/used.json",
        ),
        catalogue_ref="openlibrary:/works/OL123W",
    )
    packet = ClaimPacket(
        sweep=sweep,
        room=Room(
            length_m=None,
            width_m=None,
            height_m=None,
            floor_area_m2=None,
            wall_area_m2=None,
            shelved_wall_area_m2=None,
            scale_method="not measured",
            confidence=0,
        ),
        books=[book],
        items=[],
        totals=compute_totals([book], [], "INR"),
        review_queue=[],
    )

    report = render_report(packet)

    assert "href='frames/book.jpg'" in report
    assert "href='https://shop.example/book'" in report
    assert "href='https://ebay.example/item'" in report
    assert "500.00 INR" in report and "300.00 INR" in report
