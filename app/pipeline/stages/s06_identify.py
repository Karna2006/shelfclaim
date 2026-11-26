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

import httpx
from app.identify.catalogue import CatalogueClient, OpenLibraryGoogleBooks
from app.pipeline.context import StageContext
from rapidfuzz import fuzz


async def run(ctx: StageContext, *, max_books: int | None = None) -> Path:
    """Search catalogues for readable transcriptions and persist scored matches."""
    if max_books is not None and max_books < 1:
        raise ValueError("max_books must be positive")
    transcription_path = ctx.sweep_dir / "s05_transcriptions.json"
    if not transcription_path.is_file():
        raise FileNotFoundError("S5 transcriptions are required before catalogue matching")
    s03_path = ctx.sweep_dir / "s03_books_raw.json"
    if not s03_path.is_file():
        raise FileNotFoundError("S3 book clusters are required before catalogue matching")
    transcriptions = json.loads(transcription_path.read_text(encoding="utf-8")).get("books", {})
    book_rows = json.loads(s03_path.read_text(encoding="utf-8")).get("books", [])
    if max_books is not None:
        book_rows = book_rows[:max_books]
    injected = ctx.clients.get("catalogue")
    catalogue = (
        cast(CatalogueClient, injected) if injected else OpenLibraryGoogleBooks(ctx.settings)
    )
    semaphore = asyncio.Semaphore(5)

    async def match(
        book_id: str, transcription: dict[str, Any]
    ) -> tuple[str, dict[str, Any], dict[str, str] | None]:
        title, author, publisher = _transcribed_fields(transcription)
        unclassified_text = not title
        if unclassified_text:
            title, author = _frame_ocr_fields(transcription)
        scoring_title = title
        raw_text = str(transcription.get("spine_text_raw", "")).strip()
        line_text = " ".join(_own_lines(transcription))
        if (
            unclassified_text
            and raw_text
            and line_text
            and (normalize_catalogue_text(raw_text) != normalize_catalogue_text(line_text))
        ):
            scoring_title = raw_text
        candidates = []
        if title:
            async with semaphore:
                try:
                    candidates = await _search_candidates(catalogue, title, author, transcription)
                except (httpx.HTTPError, OSError, ValueError, TimeoutError):
                    candidates = []
        candidates = [
            candidate
            for candidate in candidates
            if candidate.get("source") and candidate.get("key")
        ]
        scored = [
            _score_candidate(
                scoring_title,
                author,
                publisher,
                float(transcription.get("legibility", 0)),
                candidate,
                ctx.settings.config.identify.weights,
                strict_title=unclassified_text,
            )
            for candidate in candidates
        ]
        scored.sort(key=lambda candidate: candidate["score"], reverse=True)
        top = scored[0] if scored else None
        matched_enough = top is not None and top["score"] >= ctx.settings.config.identify.tau_review
        if unclassified_text and top is not None:
            matched_enough = matched_enough and (
                top["features"]["title"] >= ctx.settings.config.identify.tau_accept
            )
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
        *(
            match(
                book["book_id"],
                transcriptions.get(
                    book["book_id"],
                    {"views": [], "spine_text_raw": "", "legibility": 0},
                ),
            )
            for book in book_rows
        )
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


def _frame_ocr_fields(value: dict[str, Any]) -> tuple[str, str]:
    """Separate a plausible person line from the title text without inventing words."""
    lines = _own_lines(value)
    person = (
        next((line for line in lines if _looks_like_person_name(line)), "")
        if len(lines) > 1
        else ""
    )
    title_lines = [line for line in lines if line != person] if person else lines
    title = " ".join(title_lines).strip()
    return title or str(value.get("spine_text_raw", "")).strip(), person


def _own_lines(value: dict[str, Any]) -> list[str]:
    lines = [
        str(line.get("text", "")).strip()
        for view in value.get("views", [])
        for line in view.get("lines", [])
        if str(line.get("text", "")).strip()
    ]
    if lines:
        return lines
    return [
        line.strip() for line in str(value.get("spine_text_raw", "")).split("|") if line.strip()
    ]


def _looks_like_person_name(line: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", line)
    if not 2 <= len(words) <= 4 or len(words) != len(line.split()) or not line.istitle():
        return False
    common_title_words = {"a", "an", "and", "by", "for", "in", "of", "the", "to", "with"}
    return not any(word.casefold() in common_title_words for word in words)


def _search_queries(title: str, author: str, value: dict[str, Any]) -> list[tuple[str, str]]:
    lines = _own_lines(value)
    detected_author = (
        next((line for line in lines if _looks_like_person_name(line)), author)
        if len(lines) > 1
        else author
    )
    title_lines = [line for line in lines if line != detected_author] if detected_author else lines
    longest = max(title_lines or lines, key=len) if lines else title
    proposals = [(title, author), (longest, ""), (longest, detected_author)]
    unique: list[tuple[str, str]] = []
    for proposed_title, proposed_author in proposals:
        candidate = (proposed_title.strip(), proposed_author.strip())
        if candidate[0] and candidate not in unique:
            unique.append(candidate)
    return unique


async def _search_candidates(
    catalogue: CatalogueClient,
    title: str,
    author: str,
    transcription: dict[str, Any],
) -> list[dict[str, object]]:
    """Exhaust Open Library queries before the quota-sensitive Google fallback."""
    open_library_search = getattr(catalogue, "search_open_library", None)
    google_books_search = getattr(catalogue, "search_google_books", None)
    if not callable(open_library_search):
        return await catalogue.search(title, author)

    candidates: list[dict[str, object]] = []
    rate_limited = False
    for query_title, query_author in _search_queries(title, author, transcription):
        try:
            candidates.extend(await open_library_search(query_title, query_author))
        except httpx.HTTPStatusError as exc:
            rate_limited = exc.response.status_code == 429
            break
        except (httpx.HTTPError, OSError, ValueError, TimeoutError):
            break
    if candidates or rate_limited:
        return _unique_candidates(candidates)
    if callable(google_books_search):
        try:
            return await google_books_search(title, author)
        except (httpx.HTTPError, OSError, ValueError, TimeoutError):
            return []
    return await catalogue.search(title, author)


def _unique_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    unique: dict[tuple[str, str], dict[str, object]] = {}
    for candidate in candidates:
        key = (str(candidate.get("source", "")), str(candidate.get("key", "")))
        if key[0] and key[1]:
            unique.setdefault(key, candidate)
    return list(unique.values())


def _score_candidate(
    title: str,
    author: str,
    publisher: str,
    legibility: float,
    candidate: dict[str, object],
    weights: dict[str, float],
    *,
    strict_title: bool = False,
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
    title_match = fuzz.ratio if strict_title else fuzz.token_set_ratio
    title_score = (
        title_match(normalize_catalogue_text(title), normalize_catalogue_text(candidate_title))
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
