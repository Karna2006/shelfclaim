"""Assemble, validate and report the deterministic claim packet.

Input: S3–S7 artifacts, saved frames and user statements. Output:
`claim_packet.json` plus `report.html`; room measurements stay null without 3D.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.capture.storage import list_frames
from app.packet.models import (
    Book,
    ClaimPacket,
    Dimensions,
    Item,
    ItemReplacementCost,
    Meta,
    ReplacementCost,
    ReviewEntry,
    Room,
    Sweep,
    UsedValue,
    UserStatement,
)
from app.packet.report import render_report
from app.packet.totals import compute_totals
from app.packet.validate import validate_packet
from app.pipeline.artifacts import Event
from app.pipeline.context import StageContext
from app.telemetry.events import write_event


def run(ctx: StageContext) -> Path:
    """Build a contract-validated packet from available pipeline artifacts."""
    started = time.perf_counter()
    required = (
        "s03_books_raw.json",
        "s04_measurements.json",
        "s05_transcriptions.json",
        "s06_identification.json",
        "s07_book_prices.json",
        "s08_items.json",
        "s09_room.json",
    )
    missing = [name for name in required if not (ctx.sweep_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Required packet artifacts are missing: {', '.join(missing)}")
    raw = {name: _read(ctx.sweep_dir / name) for name in required}
    sweep = Sweep.model_validate_json((ctx.sweep_dir / "sweep.json").read_text(encoding="utf-8"))
    frames = {row.seq: row for row in list_frames(ctx.sweep_dir)}
    books = _build_books(raw, frames, sweep.currency)
    items = _build_items(raw["s08_items.json"], sweep.currency)
    room = Room(
        length_m=None,
        width_m=None,
        height_m=None,
        floor_area_m2=None,
        wall_area_m2=None,
        shelved_wall_area_m2=None,
        scale_method="not measured (3D reconstruction out of scope for this build)",
        confidence=0,
        floor_area_ft2=None,
        wall_area_ft2=None,
        shelved_wall_area_ft2=None,
        shape=None,
        polygon_m=None,
        coverage_pct=None,
        method_notes="Geometry backend is disabled; room dimensions and areas are unknown.",
    )
    review = _build_review(raw)
    review.append(
        ReviewEntry(
            ref_id="room",
            reason="Room area was not measured because 3D reconstruction is out of scope.",
            code="room_not_measured",
            severity="warn",
        )
    )
    for item in items:
        review.append(
            ReviewEntry(
                ref_id=item.id,
                reason="Item needs a grounded provider price or appraisal.",
                code="needs_appraisal:item" if item.is_artwork else "price_not_found",
            )
        )
    statements = _read_statements(ctx.sweep_dir, review)
    measurements = raw["s04_measurements.json"]
    shelf_run_m = measurements.get("shelf_run_m")
    totals = compute_totals(books, items, sweep.currency, shelf_run_m=shelf_run_m)
    elapsed = time.perf_counter() - started
    ledger = ctx.ledger.to_dict()
    telemetry = {
        **ledger,
        "time_to_packet_s": round(elapsed, 6),
        "costs": ledger.get("costs", []),
    }
    packet = ClaimPacket(
        sweep=sweep,
        room=room,
        books=books,
        items=items,
        totals=totals,
        review_queue=review,
        user_statements=statements,
        meta=Meta(
            pipeline_version="phase-2-cascade",
            models={
                "agent": ctx.settings.agent_model,
                "vision": ctx.settings.vision_model,
                "geometry": "off",
            },
            telemetry=telemetry,
            assumptions=[
                "Spine counts use best-frame detection boxes.",
                "Room dimensions are not measured.",
            ],
            validation={},
        ),
    )
    validation = validate_packet(packet, ctx.sweep_dir)
    packet = packet.model_copy(
        update={"meta": packet.meta.model_copy(update={"validation": validation})}
    )
    output = ctx.sweep_dir / "claim_packet.json"
    output.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (ctx.sweep_dir / "report.html").write_text(render_report(packet), encoding="utf-8")
    if validation["passed"]:
        write_event(
            ctx.sweep_dir,
            Event(
                t_ms=0,
                type="packet_ready",
                payload={"packet": "claim_packet.json", "report": "report.html"},
            ),
        )
    return output


def _build_books(
    raw: dict[str, dict[str, Any]], frames: dict[int, Any], currency: str
) -> list[Book]:
    clusters = raw["s03_books_raw.json"].get("books", [])
    measurements = raw["s04_measurements.json"].get("books", {})
    identities = raw["s06_identification.json"].get("books", {})
    transcriptions = raw["s05_transcriptions.json"].get("books", {})
    prices = raw["s07_book_prices.json"].get("books", {})
    result = []
    for cluster in clusters:
        book_id = cluster["book_id"]
        identity = identities.get(book_id, {})
        transcription = transcriptions.get(book_id, {})
        pricing = prices.get(book_id, {})
        view = cluster["best_view"]
        frame_seq = int(view["seq"])
        frame = frames.get(frame_seq)
        chosen = identity.get("chosen") or {}
        identified = (
            identity.get("status") == "identified"
            and bool(identity.get("title"))
            and bool(chosen.get("key"))
        )
        appraisal = bool(pricing.get("appraisal", {}).get("flag"))
        status = "needs_appraisal" if appraisal else "identified" if identified else "unidentified"
        new, used = (
            _quote(pricing.get("new"), currency),
            _quote(pricing.get("used"), currency, used=True),
        )
        if status == "needs_appraisal":
            new = _quote(None, currency, status="skipped_appraisal")
            used = _quote(None, currency, status="skipped_appraisal", used=True)
        metric = measurements.get(book_id, {})
        confidence = float(identity.get("id_confidence", 0)) if identified else 0
        result.append(
            Book(
                id=book_id,
                shelf=f"{cluster['unit']}-{cluster['row']}",
                position=int(cluster["position"]),
                frame_ref=str(view["frame_ref"]),
                status=status,
                title=str(identity.get("title", "")) if identified else "",
                author=" ".join(identity.get("authors", [])) if identified else "",
                edition=str(identity.get("edition", "")) if identified else "",
                isbn=str(identity.get("isbn", "")) if identified else "",
                spine_height_cm=metric.get("height_cm"),
                spine_thickness_cm=metric.get("thickness_cm"),
                id_confidence=confidence,
                replacement_cost=ReplacementCost.model_validate(new),
                used_value=UsedValue.model_validate(used),
                frame_bbox=view.get("bbox"),
                frame_time_s=frame.t_ms / 1000 if frame else None,
                spine_text_raw=str(
                    transcription.get("spine_text_raw", identity.get("spine_text_raw", ""))
                ),
                legibility=transcription.get("legibility"),
                orientation="flat"
                if abs(float(view.get("bbox", {}).get("angle_deg", 90))) < 30
                else "upright",
                dim_method=metric.get("method", "none"),
                crop_ref=_best_crop_ref(transcription),
                catalogue_ref=f"{chosen.get('source', '')}:{chosen.get('key', '')}"
                if identified
                else None,
                appraisal_reasons=pricing.get("appraisal", {}).get("reasons", []),
            )
        )
    return result


def _quote(
    value: dict[str, Any] | None, currency: str, *, status: str | None = None, used: bool = False
) -> dict[str, Any]:
    value = value or {}
    quote = {
        key: value.get(key)
        for key in (
            "amount",
            "source",
            "url",
            "retrieved_at",
            "converted",
            "currency",
            "original_amount",
            "original_currency",
            "fx",
            "n_offers",
            "snapshot_path",
            "price_status",
        )
    }
    quote["amount"] = None if status else quote["amount"]
    quote["currency"] = quote["currency"] or currency
    quote["source"] = quote["source"] or ""
    quote["url"] = quote["url"] or ""
    quote["retrieved_at"] = quote["retrieved_at"] or ""
    quote["converted"] = quote["converted"] or False
    quote["price_status"] = status or (quote["price_status"] if quote["amount"] else "not_found")
    if used:
        quote["condition_assumed"] = value.get("condition_assumed", "Used – Good")
    return quote


def _build_review(raw: dict[str, dict[str, Any]]) -> list[ReviewEntry]:
    result = []
    for key in (
        "s03_books_raw.json",
        "s04_measurements.json",
        "s06_identification.json",
        "s07_book_prices.json",
    ):
        for entry in raw[key].get("review_queue", []):
            code = str(entry.get("code", "review_required"))
            result.append(
                ReviewEntry(
                    ref_id=str(entry.get("ref_id", "sweep")),
                    reason=code.replace("_", " "),
                    code=code,
                    evidence=entry.get("evidence"),
                )
            )
    return result


def _build_items(raw: dict[str, Any], currency: str) -> list[Item]:
    """Keep detected items with unknown dimensions and null prices in review."""
    output = []
    for row in raw.get("items", []):
        view = row["best_view"]
        output.append(
            Item(
                id=str(row["item_id"]),
                category=str(row["category"]),
                description=str(row.get("description", "")),
                brand_model=str(row.get("brand_model", "")),
                frame_ref=str(view["frame_ref"]),
                dimensions_cm=Dimensions(w=None, h=None, d=None),
                status="needs_appraisal",
                replacement_cost=ItemReplacementCost(
                    low=None,
                    high=None,
                    source="",
                    url="",
                    retrieved_at="",
                    currency=currency,
                    converted=False,
                ),
                confidence=row.get("confidence"),
                material=row.get("material"),
                frame_bbox=view.get("bbox"),
                dims_method="none",
                is_artwork=bool(row.get("is_artwork", False)),
                print_confirmed_by=None,
            )
        )
    return output


def _read_statements(sweep_dir: Path, review: list[ReviewEntry]) -> list[UserStatement]:
    path = sweep_dir / "user_statements.jsonl"
    if not path.is_file():
        return []
    statements = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            statement = UserStatement.model_validate_json(line)
            statements.append(statement)
            if not statement.resolved_to:
                review.append(
                    ReviewEntry(
                        ref_id=statement.id,
                        reason="User statement target unresolved",
                        code="unresolved_user_statement",
                    )
                )
        except ValueError:
            review.append(
                ReviewEntry(
                    ref_id=f"statement:{index}",
                    reason="User statement could not be validated",
                    code="unresolved_user_statement",
                )
            )
    return statements


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _best_crop_ref(transcription: dict[str, Any]) -> str | None:
    views = transcription.get("views", [])
    if not views:
        return None
    best = max(views, key=lambda view: (view.get("readable", False), view.get("legibility", 0)))
    return best.get("crop_ref")
