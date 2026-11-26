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
        book: dict[str, Any], transcription: dict[str, Any]
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        async with semaphore:
            matched = await identify_spine_lines(
                _line_records(transcription),
                catalogue,
                box=book.get("best_view", {}).get("bbox"),
            )
        selected = matched["chosen"]
        confidence = float(selected["id_confidence"]) if selected else 0.0
        reviews = []
        if matched["other_titles"]:
            reviews.append(
                {
                    "ref_id": book["book_id"],
                    "code": "multiple_titles_in_box",
                    "other_titles": matched["other_titles"],
                }
            )
        result = {
            "status": "identified" if selected else "unidentified",
            "chosen": selected["candidate"] if selected else None,
            "title": selected["candidate"].get("title", "") if selected else "",
            "authors": selected["candidate"].get("authors", []) if selected else [],
            "edition": "",
            "isbn": "",
            "raw_score": float(selected["raw_score"]) if selected else 0,
            "id_confidence": confidence,
            "candidates": matched["candidates"][:8],
            "spine_text_raw": transcription.get("spine_text_raw", ""),
        }
        return book["book_id"], result, reviews

    matched = await asyncio.gather(
        *(
            match(
                book,
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
        "review_queue": [review for _, _, reviews in matched for review in reviews],
        "thresholds": {
            "title_sim_min": 90,
            "author_sim_min_for_short_titles": 85,
            "minimum_words_without_author": 3,
        },
        "calibration": {"method": "title similarity with author gate", "fitted_on": None},
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


def _line_records(transcription: dict[str, Any]) -> list[dict[str, Any]]:
    lines = [
        line
        for view in transcription.get("views", [])
        for line in view.get("lines", [])
        if str(line.get("text", "")).strip()
    ]
    if lines:
        return lines
    return [
        {"text": line.strip(), "kind_guess": "other"}
        for line in str(transcription.get("spine_text_raw", "")).split("|")
        if line.strip()
    ]


async def identify_spine_lines(
    lines: list[dict[str, Any]],
    catalogue: CatalogueClient,
    *,
    box: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search each line and adjacent pair, then apply title-first evidence rules."""
    queries = _line_title_queries(lines)
    evidence: dict[tuple[str, str], list[tuple[dict[str, object], str, tuple[int, ...]]]] = {}
    for query, line_indices in queries:
        try:
            found = await catalogue.search(query, "")
        except httpx.HTTPStatusError:
            break
        except (httpx.HTTPError, OSError, ValueError, TimeoutError):
            continue
        for candidate in found:
            identity = (str(candidate.get("source", "")), str(candidate.get("key", "")))
            if all(identity):
                evidence.setdefault(identity, []).append((candidate, query, line_indices))

    candidates = []
    for matches in evidence.values():
        candidate = matches[0][0]
        title_text, title_sim, line_indices = max(
            (
                (query, _title_similarity(query, str(candidate.get("title", ""))), indices)
                for _, query, indices in matches
            ),
            key=lambda row: (row[1], -_line_box_distance(lines, row[2], box)),
        )
        authors = candidate.get("authors", [])
        authors = authors if isinstance(authors, list) else [str(authors)]
        author_sim = max(
            (
                _text_similarity(line.get("text", ""), author)
                for index, line in enumerate(lines)
                if index not in line_indices
                for author in authors
            ),
            default=0.0,
        )
        publishers = candidate.get("publishers", [])
        publishers = publishers if isinstance(publishers, list) else [str(publishers)]
        publisher_sim = max(
            (
                _text_similarity(line.get("text", ""), publisher)
                for line in lines
                if line.get("kind_guess") == "publisher"
                for publisher in publishers
            ),
            default=0.0,
        )
        title_words = len(_comparison_text(title_text).split())
        accepted = title_sim >= 90 and (author_sim >= 85 or title_words >= 3)
        distance = _line_box_distance(lines, line_indices, box)
        candidates.append(
            {
                "candidate": candidate,
                "title_sim": round(title_sim, 2),
                "author_sim": round(author_sim, 2),
                "publisher_sim": round(publisher_sim, 2),
                "raw_score": round(title_sim / 100, 4),
                "id_confidence": round(title_sim / 100, 4) if accepted else 0.0,
                "accepted": accepted,
                "matched_query": title_text,
                "line_indices": list(line_indices),
                "line_distance": distance if distance != float("inf") else None,
                "features": {
                    "title": title_sim / 100,
                    "author": author_sim / 100,
                    "publisher": publisher_sim / 100,
                },
                "score": round(title_sim / 100, 4),
            }
        )

    candidates.sort(key=lambda row: (-row["title_sim"], -row["author_sim"]))
    accepted_titles: dict[str, dict[str, Any]] = {}
    for row in candidates:
        if not row["accepted"]:
            continue
        title_key = _comparison_text(str(row["candidate"].get("title", "")))
        current = accepted_titles.get(title_key)
        if current is None or _candidate_choice_key(row, box) < _candidate_choice_key(current, box):
            accepted_titles[title_key] = row
    accepted = sorted(accepted_titles.values(), key=lambda row: _candidate_choice_key(row, box))
    chosen = accepted[0] if accepted else None
    other_titles = [str(row["candidate"].get("title", "")) for row in accepted[1:]]
    if chosen:
        reason = f"accepted title_sim={chosen['title_sim']:.1f}; " + (
            f"matching author_sim={chosen['author_sim']:.1f}"
            if chosen["author_sim"] >= 85
            else "title has at least three words"
        )
    elif candidates:
        top = candidates[0]
        reason = (
            f"rejected: title_sim={top['title_sim']:.1f} must be >=90 and require "
            "author_sim>=85 or a title of at least three words"
        )
    else:
        reason = "no catalogue candidates returned"
    return {
        "queries": queries,
        "candidates": candidates,
        "chosen": chosen,
        "other_titles": other_titles,
        "reason": reason,
    }


def _line_title_queries(lines: list[dict[str, Any]]) -> list[tuple[str, tuple[int, ...]]]:
    queries: list[tuple[str, tuple[int, ...]]] = []
    seen = set()
    for index, line in enumerate(lines):
        query = _comparison_text(str(line.get("text", "")))
        if query and query not in seen:
            queries.append((query, (index,)))
            seen.add(query)
    for index in range(len(lines) - 1):
        query = _comparison_text(
            f"{lines[index].get('text', '')} {lines[index + 1].get('text', '')}"
        )
        if query and query not in seen:
            queries.append((query, (index, index + 1)))
            seen.add(query)
    return queries


def _comparison_text(value: str) -> str:
    normalized = normalize_catalogue_text(value)
    return normalized[4:] if normalized.startswith("the ") else normalized


def _text_similarity(first: str, second: str) -> float:
    left, right = _comparison_text(first), _comparison_text(second)
    if not left or not right:
        return 0.0
    compact = fuzz.ratio(left.replace(" ", ""), right.replace(" ", ""))
    return float(max(fuzz.ratio(left, right), compact))


def _title_similarity(query: str, candidate_title: str) -> float:
    return _text_similarity(query, candidate_title)


def _line_box_distance(
    lines: list[dict[str, Any]], indices: tuple[int, ...], box: dict[str, Any] | None
) -> float:
    if not box:
        return float("inf")
    box_x = float(box.get("x", 0)) + float(box.get("w", 0)) / 2
    box_y = float(box.get("y", 0)) + float(box.get("h", 0)) / 2
    distances = []
    for index in indices:
        bbox = lines[index].get("bbox")
        if not isinstance(bbox, dict):
            continue
        x = float(bbox.get("x", 0)) + float(bbox.get("w", 0)) / 2
        y = float(bbox.get("y", 0)) + float(bbox.get("h", 0)) / 2
        distances.append(((x - box_x) ** 2 + (y - box_y) ** 2) ** 0.5)
    return min(distances, default=float("inf"))


def _candidate_choice_key(
    candidate: dict[str, Any], box: dict[str, Any] | None
) -> tuple[float, float]:
    if box:
        return (
            candidate["line_distance"] if candidate["line_distance"] is not None else float("inf"),
            -candidate["title_sim"],
        )
    return -candidate["title_sim"], -candidate["author_sim"]
