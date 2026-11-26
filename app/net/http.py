"""Fetch remote bytes for local setup tasks with a small SQLite response cache.

Input is a source URL and cache path; output is its response body. Uses httpx,
tenacity retries, a seven-day cache, and a ShelfClaim User-Agent.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_USER_AGENT = "ShelfClaim/0.1 (local model setup)"
_CACHE_TTL = timedelta(days=7)
RequestObserver = Callable[[str, int | None, bool, str | None], None]


async def fetch_bytes(
    url: str,
    cache_path: Path = Path("cache/http_cache.sqlite"),
    *,
    cache_key: str | None = None,
    on_request: RequestObserver | None = None,
    timeout_s: float = 30,
    max_retries: int = 2,
) -> bytes:
    """Return cached response bytes or fetch and cache them."""
    selected_cache_key = cache_key or url
    cached = _read_cache(selected_cache_key, cache_path)
    if cached is not None:
        if on_request is not None:
            on_request(url, 200, True, None)
        return cached

    if timeout_s <= 0 or max_retries < 0:
        raise ValueError("timeout_s must be positive and max_retries cannot be negative")
    retrying_fetch = retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(max_retries + 1),
        reraise=True,
    )(_fetch_remote)
    response_body = await retrying_fetch(url, on_request, timeout_s)
    _write_cache(selected_cache_key, response_body, cache_path)
    return response_body


async def _fetch_remote(
    url: str,
    on_request: RequestObserver | None = None,
    timeout_s: float = 30,
) -> bytes:
    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout_s,
        follow_redirects=True,
    ) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            if on_request is not None:
                on_request(url, None, False, type(exc).__name__)
            raise
        if on_request is not None:
            on_request(str(response.url), response.status_code, False, None)
        response.raise_for_status()
        return response.content


def _read_cache(url: str, cache_path: Path) -> bytes | None:
    if not cache_path.is_file():
        return None
    with sqlite3.connect(cache_path) as connection:
        _create_cache_table(connection)
        row = connection.execute(
            "SELECT body, fetched_at FROM http_cache WHERE url = ?", (url,)
        ).fetchone()
    if row is None:
        return None
    fetched_at = datetime.fromisoformat(row[1])
    if datetime.now(UTC) - fetched_at > _CACHE_TTL:
        return None
    return bytes(row[0])


def _write_cache(url: str, body: bytes, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cache_path) as connection:
        _create_cache_table(connection)
        connection.execute(
            "INSERT OR REPLACE INTO http_cache (url, body, fetched_at) VALUES (?, ?, ?)",
            (url, body, datetime.now(UTC).isoformat()),
        )


def _create_cache_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS http_cache "
        "(url TEXT PRIMARY KEY, body BLOB NOT NULL, fetched_at TEXT NOT NULL)"
    )
