"""Validate evidence paths and deterministic totals in a claim packet.

Input: a typed ClaimPacket and its sweep directory. Output: a structured gate
result; no model output participates in validation or arithmetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.packet.models import Book, ClaimPacket
from app.packet.totals import compute_totals


def validate_packet(packet: ClaimPacket, sweep_dir: Path) -> dict[str, Any]:
    """Check frame references, priced evidence, and recomputed packet totals."""
    errors: list[str] = []
    for line in [*packet.books, *packet.items]:
        if not (sweep_dir / line.frame_ref).is_file():
            errors.append(f"{line.id}: missing frame_ref {line.frame_ref}")
        if line.crop_ref and not (sweep_dir / line.crop_ref).is_file():
            errors.append(f"{line.id}: missing crop_ref {line.crop_ref}")
        if isinstance(line, Book):
            price_quotes = [line.replacement_cost, line.used_value]
        else:
            price_quotes = [line.replacement_cost]
        for quote in price_quotes:
            amount_fields = (
                [getattr(quote, "amount", None)]
                if hasattr(quote, "amount")
                else [
                    quote.low,
                    quote.high,
                ]
            )
            if any(value is not None for value in amount_fields):
                snapshot = getattr(quote, "snapshot_path", None)
                if not snapshot or not (sweep_dir / snapshot).is_file():
                    errors.append(f"{line.id}: missing price snapshot {snapshot or ''}")
    for statement in packet.user_statements:
        if statement.frame_ref and not (sweep_dir / statement.frame_ref).is_file():
            errors.append(f"{statement.id}: missing statement frame_ref {statement.frame_ref}")
    expected = compute_totals(
        packet.books,
        packet.items,
        packet.sweep.currency,
        shelf_run_m=packet.totals.shelf_run_m,
    )
    if expected.model_dump() != packet.totals.model_dump():
        errors.append("packet totals do not match deterministic recomputation")
    return {"passed": not errors, "errors": errors}
