"""Expose focused catalogue diagnostics to the local CLI.

Input: OCR text lines. Output: S6 search URLs, catalogue candidates and the
deterministic decision, without exposing any provider API key.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from app.identify.catalogue import OpenLibraryGoogleBooks
from app.pipeline.stages.s06_identify import identify_spine_lines
from app.settings import load_settings


def register_identification_commands(app: typer.Typer) -> None:
    """Register identification-specific diagnostics on the main CLI app."""

    @app.command("identify-text")
    def identify_text(lines: Annotated[list[str], typer.Argument()]) -> None:
        """Run S6 matching on supplied OCR lines and print request diagnostics."""
        catalogue = OpenLibraryGoogleBooks(load_settings())
        result = asyncio.run(
            identify_spine_lines(
                [{"text": line, "kind_guess": "other"} for line in lines], catalogue
            )
        )
        typer.echo("Queries sent:")
        if not catalogue.query_log:
            typer.echo(
                "(none; requests were suppressed after a recent 429 or no lines were usable)"
            )
        for request in catalogue.query_log:
            status = request["status"] if request["status"] is not None else request["error"]
            cache = " cached" if request["cache"] else ""
            typer.echo(f"HTTP {status}{cache} | {request['url']}")
        typer.echo("Top candidates:")
        top_candidates = result["candidates"][:5]
        if not top_candidates:
            typer.echo("(none returned)")
        for row in top_candidates:
            candidate = row["candidate"]
            typer.echo(
                f"{candidate.get('title', '')} | authors={candidate.get('authors', [])} | "
                f"title_sim={row['title_sim']:.1f} | author_sim={row['author_sim']:.1f} | "
                f"publisher_sim={row['publisher_sim']:.1f} | raw_score={row['raw_score']:.4f} | "
                f"id_confidence={row['id_confidence']:.4f}"
            )
        chosen = result["chosen"]
        if chosen:
            typer.echo(
                f"Decision: identified — {chosen['candidate'].get('title', '')} / "
                f"{chosen['candidate'].get('authors', [])}; "
                f"confidence={chosen['id_confidence']:.4f}"
            )
        else:
            typer.echo(f"Decision: unidentified — {result['reason']}")
