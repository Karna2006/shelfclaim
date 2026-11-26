"""Register the developer command for comparing shelf detector methods.

Input: Typer app and CLI arguments. Output: printed metrics and PNG paths.
Runs the offline-review workflow documented for S1 detection experiments.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer
from app.settings import load_settings
from app.vision.bakeoff import run_detection_bakeoff


def register_detection_bakeoff(app: typer.Typer) -> None:
    """Add the isolated detection comparison command to the root CLI."""

    @app.command("detection-bakeoff")
    def detection_bakeoff(
        sweep: Path,
        frames: str = typer.Option("57,62,90", "--frames"),
        two_pass_model: str = typer.Option("gemini-3.8-flash", "--two-pass-model"),
        single_pass_only: bool = typer.Option(False, "--single-pass-only"),
        two_pass_only: bool = typer.Option(False, "--two-pass-only"),
    ) -> None:
        """Compare two full-frame models and the row-crop spine detector."""
        if single_pass_only and two_pass_only:
            raise typer.BadParameter("Choose at most one method-only option")
        try:
            frame_seqs = tuple(int(value.strip()) for value in frames.split(",") if value.strip())
        except ValueError as exc:
            raise typer.BadParameter("--frames must be comma-separated sequence numbers") from exc
        results = asyncio.run(
            run_detection_bakeoff(
                sweep,
                frame_seqs,
                load_settings(),
                two_pass_model=two_pass_model,
                include_single=not two_pass_only,
                include_two_pass=not single_pass_only,
            )
        )
        typer.echo("method | frame | spines | latency_ms | model | annotated_png")
        for row in results:
            typer.echo(
                f"{row.method} | {row.seq} | {row.counts.get('book_spine', 0)} | "
                f"{row.latency_ms} | {row.model} | {row.output_path}"
            )
            if row.error:
                typer.echo(f"  error: {row.error}")
        if not os.environ.get("ROBOFLOW_API_KEY"):
            typer.echo("Roboflow skipped: ROBOFLOW_API_KEY is not set in the process environment.")
