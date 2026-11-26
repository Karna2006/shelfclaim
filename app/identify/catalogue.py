"""Search catalogue APIs through the shared cached HTTP boundary.

Input: transcribed spine title and author strings. Output: metadata candidates
with source keys; candidate text is never accepted without deterministic scoring.
"""

from __future__ import annotations

import json
import time
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from app.net.http import fetch_bytes
from app.settings import Settings

_CATALOGUE_TIMEOUT_S = 5
_CATALOGUE_MAX_RETRIES = 1
_RATE_LIMIT_COOLDOWN_S = 60


class CatalogueClient(Protocol):
    async def search(self, title: str, author: str) -> list[dict[str, object]]: ...

    async def search_open_library(self, title: str, author: str) -> list[dict[str, object]]: ...

    async def search_google_books(self, title: str, author: str) -> list[dict[str, object]]: ...


class OpenLibraryGoogleBooks:
    """Search ordered catalogues with per-run connection circuit breakers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._unavailable: set[str] = set()
        self._rate_limited_until: dict[str, float] = {}
        self.query_log: list[dict[str, object]] = []

    async def search(self, title: str, author: str) -> list[dict[str, object]]:
        for provider in self.settings.config.identify.catalogue_order:
            if (
                provider == "open_library"
                and not self.settings.config.identify.open_library_enabled
            ):
                continue
            try:
                candidates = await self._search_provider(provider, title, author)
            except (httpx.HTTPError, OSError, ValueError, TimeoutError):
                continue
            if candidates:
                return candidates
        return []

    async def search_open_library(self, title: str, author: str) -> list[dict[str, object]]:
        if not self.settings.config.identify.open_library_enabled:
            return []
        return await self._search_provider("open_library", title, author)

    async def search_google_books(self, title: str, author: str) -> list[dict[str, object]]:
        return await self._search_provider("google_books", title, author)

    async def _search_provider(
        self, provider: str, title: str, author: str
    ) -> list[dict[str, object]]:
        if self._provider_unavailable(provider):
            return []
        try:
            if provider == "google_books":
                return await self._google_books(title, author)
            return await self._open_library(title, author)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            self._unavailable.add(provider)
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                self._rate_limited_until[provider] = time.monotonic() + _RATE_LIMIT_COOLDOWN_S
            raise

    def _provider_unavailable(self, provider: str) -> bool:
        if provider in self._unavailable:
            return True
        rate_limited_until = self._rate_limited_until.get(provider, 0)
        if rate_limited_until <= time.monotonic():
            self._rate_limited_until.pop(provider, None)
            return False
        return True

    async def _open_library(self, title: str, author: str) -> list[dict[str, object]]:
        query = urlencode({"title": title, "author": author, "limit": 8})
        url = f"https://openlibrary.org/search.json?{query}"
        body = await fetch_bytes(
            url,
            self.settings.cache_db,
            on_request=self._record_request,
            timeout_s=_CATALOGUE_TIMEOUT_S,
            max_retries=_CATALOGUE_MAX_RETRIES,
        )
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
        body = await fetch_bytes(
            url,
            self.settings.cache_db,
            on_request=self._record_request,
            timeout_s=_CATALOGUE_TIMEOUT_S,
            max_retries=_CATALOGUE_MAX_RETRIES,
        )
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
        # Google Play saleInfo describes digital storefront offers; it is not pricing evidence.
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
