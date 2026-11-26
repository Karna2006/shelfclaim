"""Search catalogue APIs through the shared cached HTTP boundary.

Input: transcribed spine title and author strings. Output: metadata candidates
with source keys; candidate text is never accepted without deterministic scoring.
"""

from __future__ import annotations

import json
from typing import Protocol
from urllib.parse import urlencode

from app.net.http import fetch_bytes
from app.settings import Settings


class CatalogueClient(Protocol):
    async def search(self, title: str, author: str) -> list[dict[str, object]]: ...


class OpenLibraryGoogleBooks:
    """Query Open Library and Google Books; SQLite URL caching is shared by both."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def search(self, title: str, author: str) -> list[dict[str, object]]:
        candidates = await self._open_library(title, author)
        candidates.extend(await self._google_books(title, author))
        return candidates

    async def _open_library(self, title: str, author: str) -> list[dict[str, object]]:
        query = urlencode({"title": title, "author": author, "limit": 8})
        body = await fetch_bytes(
            f"https://openlibrary.org/search.json?{query}", self.settings.cache_db
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
        body = await fetch_bytes(
            f"https://www.googleapis.com/books/v1/volumes?{urlencode(query)}",
            self.settings.cache_db,
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
        return candidates
