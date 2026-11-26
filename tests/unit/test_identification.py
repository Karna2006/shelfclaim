from __future__ import annotations

import json
import time

import httpx
import pytest
from app.identify.catalogue import OpenLibraryGoogleBooks
from app.pipeline.context import StageContext
from app.pipeline.stages.s06_identify import (
    identify_spine_lines,
    normalize_catalogue_text,
    run,
)
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger


class EmptyCatalogue:
    async def search(self, title: str, author: str) -> list[dict[str, object]]:
        assert title == "visible fragment"
        return []


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
async def test_open_library_queries_precede_google_books_fallback() -> None:
    class OrderedCatalogue:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        async def search_open_library(self, title: str, author: str):
            self.calls.append(("openlibrary", title, author))
            return []

        async def search_google_books(self, title: str, author: str):
            self.calls.append(("google_books", title, author))
            return [{"source": "google_books", "key": "gb1", "title": title}]

    catalogue = OrderedCatalogue()
    transcription = {
        "views": [
            {
                "lines": [
                    {"text": "DEEP WORK", "kind_guess": "other"},
                    {"text": "Cal Newport", "kind_guess": "other"},
                ]
            }
        ]
    }

    results = await identify_spine_lines(transcription["views"][0]["lines"], catalogue)

    assert [call[0] for call in catalogue.calls] == [
        "openlibrary",
        "openlibrary",
        "openlibrary",
        "google_books",
    ]
    assert [call[1] for call in catalogue.calls[:3]] == [
        "deep work",
        "cal newport",
        "deep work cal newport",
    ]
    assert results["candidates"][0]["candidate"]["source"] == "google_books"


@pytest.mark.asyncio
async def test_open_library_429_prevents_google_books_fallback() -> None:
    class RateLimitedCatalogue:
        google_called = False

        async def search_open_library(self, title: str, author: str):
            del title, author
            request = httpx.Request("GET", "https://openlibrary.org")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)

        async def search_google_books(self, title: str, author: str):
            del title, author
            self.google_called = True
            return []

    catalogue = RateLimitedCatalogue()
    results = await identify_spine_lines([{"text": "DEEP WORK"}], catalogue)

    assert results["candidates"] == []
    assert not catalogue.google_called


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
    catalogue._last_429_at = time.monotonic()

    assert await catalogue.search_google_books("TITLE", "AUTHOR") == []
    assert calls == 0

    catalogue._last_429_at = time.monotonic() - 61
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
