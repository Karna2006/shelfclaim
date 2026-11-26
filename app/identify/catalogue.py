"""Search catalogue APIs through the shared cached HTTP boundary.

Input: transcribed spine title and author strings. Output: metadata candidates
with source keys; candidate text is never accepted without deterministic scoring.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from app.net.http import fetch_bytes
from app.settings import Settings


class CatalogueClient(Protocol):
    async def search(self, title: str, author: str) -> list[dict[str, object]]: ...

    async def search_open_library(self, title: str, author: str) -> list[dict[str, object]]: ...

    async def search_google_books(self, title: str, author: str) -> list[dict[str, object]]: ...


class OpenLibraryGoogleBooks:
    """Query Open Library and Google Books; SQLite URL caching is shared by both."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._last_429_at: float | None = None
        self._google_lock = asyncio.Lock()
        self.query_log: list[dict[str, object]] = []

    async def search(self, title: str, author: str) -> list[dict[str, object]]:
        candidates = await self.search_open_library(title, author)
        if candidates or self._recent_429():
            return candidates
        return await self.search_google_books(title, author)

    async def search_open_library(self, title: str, author: str) -> list[dict[str, object]]:
        try:
            return await self._open_library(title, author)
        except httpx.HTTPStatusError as exc:
            self._remember_429(exc)
            raise

    async def search_google_books(self, title: str, author: str) -> list[dict[str, object]]:
        async with self._google_lock:
            if self._recent_429():
                return []
            try:
                return await self._google_books(title, author)
            except httpx.HTTPStatusError as exc:
                self._remember_429(exc)
                raise

    def _recent_429(self) -> bool:
        return self._last_429_at is not None and time.monotonic() - self._last_429_at < 60

    def _remember_429(self, error: httpx.HTTPStatusError) -> None:
        if error.response.status_code == 429:
            self._last_429_at = time.monotonic()

    async def _open_library(self, title: str, author: str) -> list[dict[str, object]]:
        query = urlencode({"title": title, "author": author, "limit": 8})
        url = f"https://openlibrary.org/search.json?{query}"
        body = await fetch_bytes(url, self.settings.cache_db, on_request=self._record_request)
        docs = json.loads(body).get("docs", [])
        return [
            {
                "source": "openlibrary",
                "key": item.get("key", ""),
                "title": item.get("title", ""),
                "authors": item.get("author_name", []),
                "year": item.get("first_publish_year"),
                "publishers": item.get("publisher", []),
                "isbns": item.get("isbn", []),
            }
            for item in docs
            if isinstance(item, dict)
        ]

    async def _google_books(self, title: str, author: str) -> list[dict[str, object]]:
        search = f"intitle:{title} inauthor:{author}" if author else f"intitle:{title}"
        query: dict[str, str] = {"q": search, "maxResults": "8"}
        if self.settings.google_books_api_key is not None:
            query["key"] = self.settings.google_books_api_key.get_secret_value()
        url = f"https://www.googleapis.com/books/v1/volumes?{urlencode(query)}"
        body = await fetch_bytes(url, self.settings.cache_db, on_request=self._record_request)
        items = json.loads(body).get("items", [])
        candidates = []
        for item in items:
            if not isinstance(item, dict):
                continue
            volume = item.get("volumeInfo", {})
            candidates.append(
                {
                    "source": "google_books",
                    "key": item.get("id", ""),
                    "title": volume.get("title", ""),
                    "authors": volume.get("authors", []),
                    "year": volume.get("publishedDate"),
                    "publishers": [volume.get("publisher", "")],
                    "isbns": [
                        entry.get("identifier", "")
                        for entry in volume.get("industryIdentifiers", [])
                    ],
                }
            )
        return candidates

    def _record_request(
        self, url: str, status: int | None, cached: bool, error: str | None
    ) -> None:
        self.query_log.append(
            {"url": _redact_url(url), "status": status, "cache": cached, "error": error}
        )


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    params = [
        (key, "<redacted>" if key.casefold() in {"key", "api_key", "apikey"} else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment)
    )
