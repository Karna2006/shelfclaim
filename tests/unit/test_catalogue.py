from __future__ import annotations

import json

import httpx
import pytest
from app.identify.catalogue import OpenLibraryGoogleBooks
from app.settings import Settings, YamlSettings


def test_google_books_is_the_default_catalogue_and_open_library_can_be_disabled() -> None:
    defaults = YamlSettings().identify
    assert defaults.catalogue_order == ["google_books", "open_library"]
    assert defaults.open_library_enabled is True

    disabled = YamlSettings.model_validate(
        {"identify": {"catalogue_order": ["google_books"], "open_library_enabled": False}}
    )
    assert disabled.identify.open_library_enabled is False
    assert disabled.identify.catalogue_order == ["google_books"]


@pytest.mark.asyncio
async def test_google_books_results_prevent_open_library_request(monkeypatch) -> None:
    catalogue = OpenLibraryGoogleBooks(Settings(config=YamlSettings(), _env_file=None))
    open_library_calls = 0

    async def google_books(title: str, author: str) -> list[dict[str, object]]:
        del title, author
        return [{"source": "google_books", "key": "gb1", "title": "Deep Work"}]

    async def open_library(title: str, author: str) -> list[dict[str, object]]:
        nonlocal open_library_calls
        del title, author
        open_library_calls += 1
        return []

    monkeypatch.setattr(catalogue, "_google_books", google_books)
    monkeypatch.setattr(catalogue, "_open_library", open_library)

    results = await catalogue.search("Deep Work", "")

    assert results[0]["source"] == "google_books"
    assert open_library_calls == 0


@pytest.mark.asyncio
async def test_catalogue_order_setting_is_respected(monkeypatch) -> None:
    config = YamlSettings.model_validate(
        {"identify": {"catalogue_order": ["open_library", "google_books"]}}
    )
    catalogue = OpenLibraryGoogleBooks(Settings(config=config, _env_file=None))
    calls: list[str] = []

    async def google_books(title: str, author: str) -> list[dict[str, object]]:
        del title, author
        calls.append("google_books")
        return []

    async def open_library(title: str, author: str) -> list[dict[str, object]]:
        del title, author
        calls.append("open_library")
        return [{"source": "openlibrary", "key": "ol1", "title": "Deep Work"}]

    monkeypatch.setattr(catalogue, "_google_books", google_books)
    monkeypatch.setattr(catalogue, "_open_library", open_library)

    result = await catalogue.search("Deep Work", "")

    assert result[0]["source"] == "openlibrary"
    assert calls == ["open_library"]


@pytest.mark.asyncio
async def test_disabled_open_library_is_never_called(monkeypatch) -> None:
    config = YamlSettings.model_validate({"identify": {"open_library_enabled": False}})
    catalogue = OpenLibraryGoogleBooks(Settings(config=config, _env_file=None))
    open_library_calls = 0

    async def google_books(title: str, author: str) -> list[dict[str, object]]:
        del title, author
        return []

    async def open_library(title: str, author: str) -> list[dict[str, object]]:
        nonlocal open_library_calls
        del title, author
        open_library_calls += 1
        return []

    monkeypatch.setattr(catalogue, "_google_books", google_books)
    monkeypatch.setattr(catalogue, "_open_library", open_library)

    assert await catalogue.search("Deep Work", "") == []
    assert open_library_calls == 0


@pytest.mark.asyncio
async def test_google_books_connect_failure_opens_run_circuit_breaker(monkeypatch) -> None:
    catalogue = OpenLibraryGoogleBooks(Settings(config=YamlSettings(), _env_file=None))
    calls = 0

    async def disconnected(title: str, author: str) -> list[dict[str, object]]:
        nonlocal calls
        del title, author
        calls += 1
        request = httpx.Request("GET", "https://books.googleapis.com")
        raise httpx.ConnectError("offline", request=request)

    async def open_library(title: str, author: str) -> list[dict[str, object]]:
        del title, author
        return [{"source": "openlibrary", "key": "ol1", "title": "Deep Work"}]

    monkeypatch.setattr(catalogue, "_google_books", disconnected)
    monkeypatch.setattr(catalogue, "_open_library", open_library)

    first = await catalogue.search("Deep Work", "")
    second = await catalogue.search("The One Thing", "")

    assert first[0]["source"] == second[0]["source"] == "openlibrary"
    assert calls == 1
    assert "google_books" in catalogue._unavailable


@pytest.mark.asyncio
async def test_catalogue_requests_use_five_second_timeout_and_one_retry(monkeypatch) -> None:
    catalogue = OpenLibraryGoogleBooks(Settings(config=YamlSettings(), _env_file=None))
    observed: dict[str, object] = {}

    async def fail_connect(url: str, cache_path, **kwargs) -> bytes:
        del url, cache_path
        observed.update(kwargs)
        request = httpx.Request("GET", "https://books.googleapis.com")
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr("app.identify.catalogue.fetch_bytes", fail_connect)
    with pytest.raises(httpx.ConnectError):
        await catalogue.search_google_books("Deep Work", "")

    assert observed["timeout_s"] == 5
    assert observed["max_retries"] == 1


@pytest.mark.asyncio
async def test_google_books_sale_info_is_not_returned_as_price(monkeypatch) -> None:
    catalogue = OpenLibraryGoogleBooks(Settings(config=YamlSettings(), _env_file=None))
    payload = {
        "items": [
            {
                "id": "volume-1",
                "volumeInfo": {
                    "title": "Deep Work",
                    "authors": ["Cal Newport"],
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9781455586691"}],
                },
                "saleInfo": {"saleability": "FOR_SALE", "listPrice": {"amount": 9.99}},
            }
        ]
    }

    async def response(url: str, cache_path, **kwargs) -> bytes:
        del url, cache_path, kwargs
        return json.dumps(payload).encode()

    monkeypatch.setattr("app.identify.catalogue.fetch_bytes", response)

    candidates = await catalogue.search_google_books("Deep Work", "")

    assert candidates[0]["isbns"] == ["9781455586691"]
    assert "saleInfo" not in candidates[0]
    assert "price" not in candidates[0]
