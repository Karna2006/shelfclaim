"""Match transcription evidence to catalogue metadata conservatively.

Input: verbatim S5 text and Open Library/Google Books candidates. Output:
`s06_identification.json`; unmatched identity fields remain empty, per §6.
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, cast

from app.identify.catalogue import CatalogueClient, OpenLibraryGoogleBooks
from app.pipeline.context import StageContext
from rapidfuzz import fuzz


async def run(ctx: StageContext) -> Path:
    """Search catalogues for readable transcriptions and persist scored matches."""
    transcription_path = ctx.sweep_dir / "s05_transcriptions.json"
    if not transcription_path.is_file():
        raise FileNotFoundError("S5 transcriptions are required before catalogue matching")
    raw = json.loads(transcription_path.read_text(encoding="utf-8"))
    injected = ctx.clients.get("catalogue")
    catalogue = (
        cast(CatalogueClient, injected) if injected else OpenLibraryGoogleBooks(ctx.settings)
    )
    semaphore = asyncio.Semaphore(5)

    async def match(book_id: str, transcription: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        title, author, publisher = _transcribed_fields(transcription)
        candidates = []
        if title:
            async with semaphore:
                try:
                    candidates = await catalogue.search(title, author)
                except (OSError, ValueError, TimeoutError):
                    candidates = []
        candidates = [
            candidate
            for candidate in candidates
            if candidate.get("source") and candidate.get("key")
        ]
        scored = [
            _score_candidate(
                title,
                author,
                publisher,
                float(transcription.get("legibility", 0)),
                candidate,
                ctx.settings.config.identify.weights,
            )
            for candidate in candidates
        ]
        scored.sort(key=lambda candidate: candidate["score"], reverse=True)
        top = scored[0] if scored else None
        matched_enough = top is not None and top["score"] >= ctx.settings.config.identify.tau_review
        status = "identified" if matched_enough else "unidentified"
        result = {
            "status": status,
            "chosen": top["candidate"] if matched_enough else None,
            "title": top["candidate"].get("title", "") if matched_enough else "",
            "authors": top["candidate"].get("authors", []) if matched_enough else [],
            "edition": "",
            "isbn": "",
            "raw_score": top["score"] if top else 0,
            "id_confidence": top["score"] if matched_enough else 0,
            "candidates": scored[:8],
            "spine_text_raw": transcription.get("spine_text_raw", ""),
        }
        review = (
            {"ref_id": book_id, "code": "low_id_confidence"}
            if matched_enough and top["score"] < ctx.settings.config.identify.tau_accept
            else None
        )
        return book_id, result, review

    matched = await asyncio.gather(
        *(match(book_id, value) for book_id, value in raw.get("books", {}).items())
    )
    output_doc = {
        "books": {book_id: result for book_id, result, _ in matched},
        "review_queue": [review for _, _, review in matched if review is not None],
        "thresholds": {
            "accept": ctx.settings.config.identify.tau_accept,
            "review": ctx.settings.config.identify.tau_review,
        },
        "calibration": {"method": "configured weighted fuzzy score", "fitted_on": None},
    }
    output = ctx.sweep_dir / "s06_identification.json"
    output.write_text(json.dumps(output_doc, indent=2) + "\n", encoding="utf-8")
    return output


def normalize_catalogue_text(value: str) -> str:
    """Fold accents, punctuation and whitespace for reproducible fuzzy matching."""
    separated = "".join(
        " " if unicodedata.category(character).startswith(("P", "Z")) else character
        for character in value
    )
    folded = unicodedata.normalize("NFKD", separated).encode("ascii", "ignore").decode().casefold()
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def _transcribed_fields(value: dict[str, Any]) -> tuple[str, str, str]:
    title_lines, author_lines, publisher_lines = [], [], []
    for view in value.get("views", []):
        for line in view.get("lines", []):
            kind = line.get("kind_guess")
            target = {
                "title": title_lines,
                "author": author_lines,
                "publisher": publisher_lines,
            }.get(kind)
            if target is not None:
                target.append(str(line.get("text", "")))
    return (
        " ".join(title_lines).strip(),
        " ".join(author_lines).strip(),
        " ".join(publisher_lines).strip(),
    )


def _score_candidate(
    title: str,
    author: str,
    publisher: str,
    legibility: float,
    candidate: dict[str, object],
    weights: dict[str, float],
) -> dict[str, Any]:
    candidate_title = str(candidate.get("title", ""))
    candidate_authors = candidate.get("authors", [])
    author_text = (
        " ".join(candidate_authors)
        if isinstance(candidate_authors, list)
        else str(candidate_authors)
    )
    publishers = candidate.get("publishers", [])
    publisher_text = " ".join(publishers) if isinstance(publishers, list) else str(publishers)
    title_score = (
        fuzz.token_set_ratio(
            normalize_catalogue_text(title), normalize_catalogue_text(candidate_title)
        )
        / 100
    )
    author_score = (
        fuzz.token_set_ratio(
            normalize_catalogue_text(author), normalize_catalogue_text(author_text)
        )
        / 100
        if author
        else 0.0
    )
    weight_title = weights.get("title", 0.55)
    publisher_score = (
        fuzz.token_set_ratio(
            normalize_catalogue_text(publisher), normalize_catalogue_text(publisher_text)
        )
        / 100
        if publisher
        else 0.0
    )
    active = {
        "title": weight_title,
        "author": weights.get("author", 0.25) if author else 0,
        "publisher": weights.get("publisher", 0.10) if publisher else 0,
        "legibility": weights.get("legibility", 0.10),
    }
    features = {
        "title": title_score,
        "author": author_score,
        "publisher": publisher_score,
        "legibility": legibility,
    }
    denominator = sum(active.values())
    score = (
        sum(features[name] * weight for name, weight in active.items()) / denominator
        if denominator
        else 0
    )
    return {
        "score": round(score, 4),
        "features": features,
        "candidate": candidate,
    }
