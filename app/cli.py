"""Typer commands for the local ShelfClaim developer workflow.

Input: CLI arguments. Output: server startup, printable calibration cards, or
explicit phase stubs. Implements `docs/06_USER_FLOWS.md` §6 and Phase 0.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import cv2
import typer
import uvicorn
from app.capture.face_audit import create_face_contact_sheet
from app.capture.marker_pdf import generate_marker_pdf
from app.capture.storage import list_frames
from app.capture.summary import summarize_frames
from app.capture.yunet_model import download_yunet_model
from app.evaluation import evaluate_sweep
from app.live.benchmark import benchmark_models
from app.live.terminal import run_agent_chat
from app.pipeline.artifacts import DetectionsDoc, Event
from app.pipeline.orchestrator import run_pipeline
from app.pipeline.stages.s07_price_books import price_sweep
from app.settings import Settings, load_settings
from app.telemetry.events import write_event
from app.vision.detect_frame import detect_frame as detect_single_frame

app = typer.Typer(no_args_is_help=True, help="ShelfClaim development commands")


@app.command()
def serve(port: int = typer.Option(8000, min=1, max=65535), reload: bool = False) -> None:
    """Serve the phone web app and local API."""
    uvicorn.run("app.server.main:app", host="0.0.0.0", port=port, reload=reload)


@app.command("make-markers")
def make_markers(
    ids: Annotated[tuple[int, int, int], typer.Option("--ids")] = (0, 1, 2),
    size_mm: Annotated[float, typer.Option("--size-mm", min=0.1)] = 100.0,
    out: Annotated[Path, typer.Option("--out")] = Path("markers.pdf"),
) -> None:
    """Create A4 ArUco calibration cards with a print-scale ruler on each page."""
    output = generate_marker_pdf(ids, size_mm, out)
    typer.echo(f"Created {len(ids)} A4 marker pages at {output}; print at actual size.")


@app.command()
def replay(
    sweep: Path,
    until: str | None = None,
    max_keyframes: Annotated[int | None, typer.Option("--max-keyframes", min=1, max=60)] = None,
    limit_books: Annotated[int | None, typer.Option("--limit-books", min=1, max=1000)] = None,
    limit: Annotated[int, typer.Option("--limit", min=0, max=40)] = 10,
) -> None:
    """Run the sweep pipeline through S1, S3, S6, S7, or the final packet stage."""
    if until not in {None, "s01", "s03", "s06", "s07", "s10"}:
        raise typer.BadParameter("until must be s01, s03, s06, s07, or s10")
    settings = load_settings()
    try:
        output = asyncio.run(
            run_pipeline(
                sweep,
                settings,
                until=until or "s10",
                max_keyframes=max_keyframes,
                max_books=limit_books,
                price_limit=limit,
            )
        )
    except Exception as exc:
        if sweep.is_dir():
            write_event(
                sweep,
                Event(
                    t_ms=0,
                    type="error",
                    payload={
                        "stage": until or "s10",
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    },
                ),
            )
        typer.echo(f"Replay blocked: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Pipeline reached {until or 's10'}: {output}")
    if (until or "s10") == "s01":
        _print_detection_keyframe_stats(sweep)
    elif until == "s03":
        _print_s03_counts(sweep)
    elif until == "s06":
        _print_s06_books(sweep, limit_books)
    elif until == "s07":
        _print_s07_prices(sweep)


def _print_detection_keyframe_stats(sweep: Path) -> None:
    document = DetectionsDoc.model_validate_json(
        (sweep / "s01_detections.json").read_text(encoding="utf-8")
    )
    typer.echo("seq | model | latency_ms | #spines | #shelf_boards | #items")
    for row in document.keyframe_stats:
        typer.echo(
            f"{row.seq} | {row.model} | {row.latency_ms} | {row.spine_count} | "
            f"{row.shelf_board_count} | {row.item_count}"
        )


def _print_s03_counts(sweep: Path) -> None:
    document = json.loads((sweep / "s03_books_raw.json").read_text(encoding="utf-8"))
    frame_paths = {frame.seq: frame.path for frame in list_frames(sweep)}
    rows = _format_s03_count_rows(document, frame_paths)
    typer.echo("unit | row | count | best_frame | candidate_min | candidate_max")
    if not rows:
        typer.echo("No unit rows formed: S1 did not detect complete shelf-unit rows.")
        return
    for row in rows:
        typer.echo(row)


def _format_s03_count_rows(document: dict[str, Any], frame_paths: dict[int, str]) -> list[str]:
    formatted = []
    for unit in document.get("units", []):
        for row in unit.get("rows", []):
            candidates = [candidate["count"] for candidate in row.get("candidate_counts", [])]
            best_seq = row.get("best_frame_seq")
            best_path = frame_paths.get(best_seq, "frame path unavailable")
            best_frame = f"{best_seq} ({best_path})"
            minimum = min(candidates) if candidates else "n/a"
            maximum = max(candidates) if candidates else "n/a"
            formatted.append(
                f"{unit['unit']} | {row['row']} | {row['count']} | {best_frame} | "
                f"{minimum} | {maximum}"
            )
    return formatted


def _print_s06_books(sweep: Path, limit: int | None) -> None:
    transcriptions = json.loads(
        (sweep / "s05_transcriptions.json").read_text(encoding="utf-8")
    ).get("books", {})
    identifications = json.loads(
        (sweep / "s06_identification.json").read_text(encoding="utf-8")
    ).get("books", {})
    book_ids = list(identifications)
    if limit is not None:
        book_ids = book_ids[:limit]
    typer.echo("book id | spine text read | identified title/author | confidence | status")
    if not book_ids:
        typer.echo("No S3 book rows to transcribe or identify.")
        return
    for book_id in book_ids:
        transcription = transcriptions.get(book_id, {})
        identification = identifications[book_id]
        authors = identification.get("authors", [])
        author_text = ", ".join(authors) if isinstance(authors, list) else str(authors)
        title = identification.get("title", "")
        title_author = " — ".join(value for value in (title, author_text) if value) or "—"
        spine_text = transcription.get("spine_text_raw", "") or "—"
        confidence = identification.get("id_confidence", 0)
        status = identification.get("status", "unidentified")
        typer.echo(f"{book_id} | {spine_text} | {title_author} | {confidence} | {status}")


def _print_s07_prices(sweep: Path) -> None:
    identities = json.loads((sweep / "s06_identification.json").read_text(encoding="utf-8")).get(
        "books", {}
    )
    prices = json.loads((sweep / "s07_book_prices.json").read_text(encoding="utf-8")).get(
        "books", {}
    )
    typer.echo(
        "title | new price | new source | new URL | used price | used source | used URL | converted"
    )
    if not prices:
        typer.echo("No identified books to price.")
        return
    for book_id, quotes in prices.items():
        title = identities.get(book_id, {}).get("title", "") or "Unidentified spine"
        new, used = quotes.get("new", {}), quotes.get("used", {})
        typer.echo(_format_s07_price_row(title, new, used))


def _format_s07_price_row(title: str, new: dict[str, Any], used: dict[str, Any]) -> str:
    return (
        f"{title} | {_price_value(new)} | {new.get('source') or '—'} | "
        f"{new.get('url') or '—'} | {_price_value(used)} | "
        f"{used.get('source') or '—'} | {used.get('url') or '—'} | "
        f"{bool(used.get('converted', False))}"
    )


def _price_value(quote: dict[str, Any]) -> str:
    amount = quote.get("amount")
    if amount is None:
        return "—"
    return f"{amount} {quote.get('currency') or ''}".strip()


@app.command("debug-boxes")
def debug_boxes(sweep: Path) -> None:
    """Save up to five frame previews with S1 boxes drawn for review."""
    detection_path = sweep / "s01_detections.json"
    if not detection_path.is_file():
        raise typer.BadParameter("Run replay --until s01 first")
    detections = DetectionsDoc.model_validate_json(detection_path.read_text(encoding="utf-8"))
    records = {record.seq: record for record in list_frames(sweep)}
    out_dir = sweep / "debug_boxes"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for seq, boxes in sorted(detections.frames.items()):
        record = records.get(seq)
        if record is None:
            continue
        image = cv2.imread(str(sweep / record.path))
        if image is None:
            continue
        for detection in boxes:
            box = detection.box_px
            rect = ((box.x + box.w / 2, box.y + box.h / 2), (box.w, box.h), box.angle_deg)
            points = cv2.boxPoints(rect).astype("int32")
            cv2.polylines(image, [points], True, (40, 220, 40), 2)
            cv2.putText(
                image,
                detection.cls,
                (box.x, max(18, box.y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (40, 220, 40),
                1,
            )
        output = out_dir / f"f_{seq:06d}_boxes.jpg"
        cv2.imwrite(str(output), image)
        typer.echo(str(output))
        saved += 1
        if saved >= 5:
            break
    typer.echo(f"Saved {saved} debug frames under {out_dir}")


@app.command("detect-frame")
def detect_frame_command(
    jpg: Path,
    out: Annotated[Path, typer.Option("--out")],
) -> None:
    """Detect objects in one JPG and save an annotated PNG preview."""
    try:
        result = asyncio.run(detect_single_frame(jpg, out, load_settings()))
    except Exception as exc:
        typer.echo(
            json.dumps(
                {
                    "error": "frame_detection_failed",
                    "exception_type": type(exc).__name__,
                    "detail": str(exc),
                },
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.to_dict(), indent=2))


@app.command("inspect-sweep")
def inspect_sweep(sweep: Path) -> None:
    """List stored frame paths and measured QC for a sweep."""
    records = list_frames(sweep)
    for record in records:
        typer.echo(
            f"seq={record.seq} path={record.path} blur={record.blur} glare={record.glare} "
            f"exposure={record.exposure} gyro_dps={record.gyro_dps} "
            f"markers={[marker.id for marker in record.markers]} "
            f"faces_blurred={record.faces_blurred}"
        )
    summary = summarize_frames(records, load_settings().config.capture)
    percentages = " ".join(
        f"{category}={summary.percentages[category]:.1f}%"
        for category in ("ok", "blurry", "fast", "glare", "dark", "bright")
    )
    typer.echo(
        f"Summary: frames={summary.frame_count} duration={summary.duration_s:.2f}s "
        f"fps={summary.fps:.2f} {percentages} markers_seen={list(summary.markers_seen)} "
        "(dark includes low_light_blur)"
    )


@app.command("inspect-faces")
def inspect_faces(sweep: Path) -> None:
    """Save a contact sheet showing detected face boxes for every frame."""
    output = create_face_contact_sheet(sweep)
    typer.echo(f"Face audit contact sheet saved to {output}")


@app.command("download-yunet")
def download_yunet() -> None:
    """Download the checksum-pinned YuNet face detector model into models/."""
    model_path = asyncio.run(download_yunet_model())
    typer.echo(f"Verified YuNet model saved to {model_path}")


@app.command("check-llm")
def check_llm() -> None:
    """Benchmark one text generation call for AGENT_MODEL and VISION_MODEL."""
    for result in asyncio.run(benchmark_models(load_settings())):
        status = "OK" if result.ok else "FAIL"
        details = f"text={result.response_text!r}" if result.ok else f"error={result.error_type}"
        typer.echo(f"{status} {result.model} latency={result.latency_s:.2f}s {details}")


@app.command("agent-chat")
def agent_chat() -> None:
    """Run the real live agent in a terminal, loading settings and .env normally."""
    settings = load_settings()
    if settings.google_api_key is None:
        raise typer.BadParameter("Set GOOGLE_API_KEY in the process environment first")
    asyncio.run(run_agent_chat(settings))


@app.command()
def stage(name: str, sweep: Annotated[Path, typer.Option("--sweep")]) -> None:
    del name, sweep
    typer.echo("not implemented in phase 0")


@app.command()
def reprice(
    sweep: Annotated[Path, typer.Option("--sweep")],
    country: Annotated[str, typer.Option("--country")],
    limit: int = typer.Option(10, min=1),
) -> None:
    """Price grounded catalogue matches with a bounded provider search count."""
    if not 0 <= limit <= 40:
        raise typer.BadParameter("limit must be between 0 and 40")
    if not (sweep / "s06_identification.json").is_file():
        typer.echo("Repricing blocked: S6 identification artifact is missing.", err=True)
        raise typer.Exit(code=1)
    settings = load_settings()
    try:
        output = asyncio.run(
            price_sweep(
                sweep,
                settings,
                _pricing_client(settings),
                country=country,
                limit=limit,
            )
        )
    except Exception as exc:
        typer.echo(f"Repricing blocked: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    result = json.loads(output.read_text(encoding="utf-8"))
    typer.echo("Book | New | Used | Status")
    for book_id, row in result["books"].items():
        new, used = row.get("new", {}), row.get("used", {})
        typer.echo(
            f"{book_id} | {new.get('amount')} {new.get('currency')} | "
            f"{used.get('amount')} {used.get('currency')} | "
            f"{new.get('price_status')}/{used.get('price_status')}"
        )
    typer.echo(f"Evidence and results: {output} (SerpAPI searches={result['searches_used']})")


def _pricing_client(settings: Settings) -> object:
    from app.pricing.providers.serpapi import SerpApiProvider

    return SerpApiProvider(settings)


@app.command()
def evaluate(
    sweep: Annotated[Path, typer.Option("--sweep")],
    gt: Annotated[Path, typer.Option("--gt")],
    out: Annotated[Path, typer.Option("--out")],
) -> None:
    output = evaluate_sweep(sweep, gt, out)
    typer.echo(f"Evaluation report: {output}")


@app.command()
def calibrate(
    sweep: Annotated[Path, typer.Option("--sweep")],
    gt: Annotated[Path, typer.Option("--gt")],
) -> None:
    del sweep, gt
    typer.echo("not implemented in phase 0")


@app.command("ingest-video")
def ingest_video(path: Path) -> None:
    del path
    typer.echo("not implemented in phase 0")


if __name__ == "__main__":
    app()
