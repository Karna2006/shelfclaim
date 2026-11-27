from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from app.identify.catalogue import OpenLibraryGoogleBooks
from app.pipeline.context import StageContext
from app.pipeline.stages.s06_identify import (
    _mark_identified_duplicates,
    normalize_catalogue_text,
    run,
)
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger


class EmptyCatalogue:
    async def search(self, title: str, author: str) -> list[dict[str, object]]:
        assert title == "visible fragment"
        return []


def test_ocr_books_with_same_title_and_overlapping_nearby_views_are_deduplicated() -> None:
    first = _identified_result([{"seq": 1, "t_ms": 1000, "bbox": {"x": 10, "w": 40}}])
    duplicate = _identified_result([{"seq": 2, "t_ms": 2000, "bbox": {"x": 12, "w": 40}}])
    separate_position = _identified_result([{"seq": 2, "t_ms": 2000, "bbox": {"x": 140, "w": 40}}])
    rows = [
        ("b_0001", first, [], []),
        ("b_0002", duplicate, [], []),
        ("b_0003", separate_position, [], []),
    ]

    _mark_identified_duplicates(rows, max_gap_ms=5000, min_x_overlap=0.5)

    assert first["status"] == "identified"
    assert duplicate["status"] == "duplicate"
    assert duplicate["duplicate_of"] == "b_0001"
    assert separate_position["status"] == "identified"


def _identified_result(views: list[dict[str, object]]) -> dict[str, object]:
    return {
        "status": "identified",
        "title": "Deep Work",
        "unit": "A",
        "row": 1,
        "candidate_views": views,
    }


def test_catalogue_normalization_folds_accents_and_punctuation() -> None:
    assert normalize_catalogue_text("Le Thé—Book, Vol. 2") == "le the book vol 2"


@pytest.mark.asyncio
async def test_unidentified_book_keeps_identity_fields_empty(tmp_path) -> None:
    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps({"books": [{"book_id": "b_0001"}]}), encoding="utf-8"
    )
    (tmp_path / "s05_transcriptions.json").write_text(
        json.dumps(
            {
                "books": {
                    "b_0001": {
                        "spine_text_raw": "VISIBLE FRAGMENT",
                        "legibility": 0.8,
                        "views": [{"lines": [{"kind_guess": "title", "text": "VISIBLE FRAGMENT"}]}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(config=YamlSettings(), _env_file=None)
    context = StageContext(tmp_path, settings, Ledger(), {"catalogue": EmptyCatalogue()})

    output = await run(context)

    book = json.loads(output.read_text(encoding="utf-8"))["books"]["b_0001"]
    assert book["status"] == "unidentified"
    assert (book["title"], book["authors"], book["edition"], book["isbn"]) == ("", [], "", "")
    assert book["id_confidence"] == 0


@pytest.mark.asyncio
async def test_missing_transcription_is_explicitly_unidentified(tmp_path) -> None:
    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps({"books": [{"book_id": "b_0001"}]}), encoding="utf-8"
    )
    (tmp_path / "s05_transcriptions.json").write_text('{"books": {}}', encoding="utf-8")
    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        Ledger(),
        {"catalogue": EmptyCatalogue()},
    )

    output = await run(context)

    book = json.loads(output.read_text(encoding="utf-8"))["books"]["b_0001"]
    assert book["status"] == "unidentified"
    assert (book["title"], book["authors"], book["edition"], book["isbn"]) == ("", [], "", "")
    assert book["spine_text_raw"] == ""


@pytest.mark.asyncio
async def test_catalogue_http_quota_error_leaves_book_unidentified(tmp_path) -> None:
    class QuotaLimitedCatalogue:
        async def search(self, title: str, author: str) -> list[dict[str, object]]:
            del title, author
            request = httpx.Request("GET", "https://catalogue.invalid")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("quota exhausted", request=request, response=response)

    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps({"books": [{"book_id": "b_0001"}]}), encoding="utf-8"
    )
    (tmp_path / "s05_transcriptions.json").write_text(
        json.dumps(
            {
                "books": {
                    "b_0001": {
                        "spine_text_raw": "VISIBLE FRAGMENT",
                        "legibility": 0.9,
                        "views": [{"lines": [{"kind_guess": "other", "text": "VISIBLE FRAGMENT"}]}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        Ledger(),
        {"catalogue": QuotaLimitedCatalogue()},
    )

    output = await run(context)

    book = json.loads(output.read_text(encoding="utf-8"))["books"]["b_0001"]
    assert book["status"] == "unidentified"
    assert (book["title"], book["authors"]) == ("", [])


@pytest.mark.asyncio
async def test_google_books_is_primary_and_open_library_is_fallback(monkeypatch) -> None:
    catalogue = OpenLibraryGoogleBooks(Settings(config=YamlSettings(), _env_file=None))
    calls: list[str] = []

    async def google_books(title: str, author: str):
        del title, author
        calls.append("google_books")
        return []

    async def open_library(title: str, author: str):
        del title, author
        calls.append("open_library")
        return [{"source": "openlibrary", "key": "ol1", "title": "Deep Work"}]

    monkeypatch.setattr(catalogue, "_google_books", google_books)
    monkeypatch.setattr(catalogue, "_open_library", open_library)
    results = await catalogue.search("Deep Work", "Cal Newport")

    assert calls == ["google_books", "open_library"]
    assert results[0]["source"] == "openlibrary"


@pytest.mark.asyncio
async def test_google_books_429_falls_back_to_open_library(monkeypatch) -> None:
    catalogue = OpenLibraryGoogleBooks(Settings(config=YamlSettings(), _env_file=None))
    open_library_calls = 0

    async def rate_limited_google(title: str, author: str):
        del title, author
        request = httpx.Request("GET", "https://books.googleapis.com")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    async def open_library(title: str, author: str):
        nonlocal open_library_calls
        del title, author
        open_library_calls += 1
        return [{"source": "openlibrary", "key": "ol1", "title": "Deep Work"}]

    monkeypatch.setattr(catalogue, "_google_books", rate_limited_google)
    monkeypatch.setattr(catalogue, "_open_library", open_library)

    result = await catalogue.search("Deep Work", "")

    assert result[0]["source"] == "openlibrary"
    assert open_library_calls == 1


@pytest.mark.asyncio
async def test_catalogue_connect_failure_opens_circuit_for_concurrent_queries(monkeypatch) -> None:
    catalogue = OpenLibraryGoogleBooks(Settings(config=YamlSettings(), _env_file=None))
    calls = {"google_books": 0, "open_library": 0}

    async def fail_google(title: str, author: str):
        del title, author
        calls["google_books"] += 1
        raise httpx.ConnectError("offline")

    async def fail_open_library(title: str, author: str):
        del title, author
        calls["open_library"] += 1
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(catalogue, "_google_books", fail_google)
    monkeypatch.setattr(catalogue, "_open_library", fail_open_library)

    results = await asyncio.gather(*(catalogue.search(f"title {index}", "") for index in range(5)))

    assert results == [[], [], [], [], []]
    assert calls == {"google_books": 1, "open_library": 1}


@pytest.mark.asyncio
async def test_recent_google_books_429_suppresses_requests_for_one_minute(monkeypatch) -> None:
    catalogue = OpenLibraryGoogleBooks(Settings(config=YamlSettings(), _env_file=None))
    calls = 0

    async def fake_google_books(title: str, author: str):
        nonlocal calls
        del title, author
        calls += 1
        return []

    monkeypatch.setattr(catalogue, "_google_books", fake_google_books)
    catalogue._rate_limited_until["google_books"] = time.monotonic() + 60

    assert await catalogue.search_google_books("TITLE", "AUTHOR") == []
    assert calls == 0

    catalogue._rate_limited_until["google_books"] = time.monotonic() - 1
    assert await catalogue.search_google_books("TITLE", "AUTHOR") == []
    assert calls == 1


@pytest.mark.asyncio
async def test_two_word_title_needs_a_matching_author_line(tmp_path) -> None:
    class CatalogueWithPartialTitle:
        async def search(self, title: str, author: str) -> list[dict[str, object]]:
            assert title == "one thing"
            del author
            return [
                {
                    "title": "The One Thing",
                    "authors": ["Gary Keller"],
                    "publishers": [],
                    "source": "openlibrary",
                    "key": "/works/OL123W",
                }
            ]

    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps({"books": [{"book_id": "b_0001"}]}), encoding="utf-8"
    )
    (tmp_path / "s05_transcriptions.json").write_text(
        json.dumps(
            {
                "books": {
                    "b_0001": {
                        "spine_text_raw": "THE ONE THING",
                        "legibility": 0.98,
                        "views": [{"lines": [{"kind_guess": "other", "text": "THE ONE THING"}]}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        Ledger(),
        {"catalogue": CatalogueWithPartialTitle()},
    )

    output = await run(context)

    book = json.loads(output.read_text(encoding="utf-8"))["books"]["b_0001"]
    assert book["status"] == "unidentified"
    assert book["title"] == ""
