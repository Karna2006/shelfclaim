"""Fetch remote bytes for local setup tasks with a small SQLite response cache.

Input is a source URL and cache path; output is its response body. Uses httpx,
tenacity retries, a seven-day cache, and a ShelfClaim User-Agent.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_USER_AGENT = "ShelfClaim/0.1 (local model setup)"
_CACHE_TTL = timedelta(days=7)
RequestObserver = Callable[[str, int | None, bool, str | None], None]


@dataclass(frozen=True)
class _CacheRecord:
    body: bytes
    status: int


async def fetch_bytes(
    url: str,
    cache_path: Path = Path("cache/http_cache.sqlite"),
    *,
    cache_key: str | None = None,
    on_request: RequestObserver | None = None,
    timeout_s: float = 30,
    max_retries: int = 2,
    cache_ttl: timedelta | None = _CACHE_TTL,
    cache_http_errors: bool = False,
) -> bytes:
    """Return cached response bytes or fetch and cache them."""
    selected_cache_key = cache_key or url
    cached = _read_cache(selected_cache_key, cache_path, cache_ttl)
    if cached is not None:
        if on_request is not None:
            on_request(
                url,
                cached.status,
                True,
                "cached_http_status" if cached.status >= 400 else None,
            )
        response = httpx.Response(
            cached.status,
            content=cached.body,
            request=httpx.Request("GET", url),
        )
        response.raise_for_status()
        return cached.body

    if timeout_s <= 0 or max_retries < 0:
        raise ValueError("timeout_s must be positive and max_retries cannot be negative")
    retrying_fetch = retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(max_retries + 1),
        reraise=True,
    )(_fetch_remote)
    response = await retrying_fetch(url, on_request, timeout_s)
    if on_request is not None:
        on_request(str(response.url), response.status_code, False, None)
    if response.status_code < 400 or cache_http_errors:
        _write_cache(selected_cache_key, response.content, response.status_code, cache_path)
    response.raise_for_status()
    return response.content


async def _fetch_remote(
    url: str,
    on_request: RequestObserver | None = None,
    timeout_s: float = 30,
) -> httpx.Response:
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
        return response


def _read_cache(url: str, cache_path: Path, cache_ttl: timedelta | None) -> _CacheRecord | None:
    if not cache_path.is_file():
        return None
    with sqlite3.connect(cache_path) as connection:
        _create_cache_table(connection)
        row = connection.execute(
            "SELECT body, fetched_at, status FROM http_cache WHERE url = ?", (url,)
        ).fetchone()
    if row is None:
        return None
    fetched_at = datetime.fromisoformat(row[1])
    if cache_ttl is not None and datetime.now(UTC) - fetched_at > cache_ttl:
        return None
    return _CacheRecord(body=bytes(row[0]), status=int(row[2]))


def _write_cache(url: str, body: bytes, status: int, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cache_path) as connection:
        _create_cache_table(connection)
        connection.execute(
            "INSERT OR REPLACE INTO http_cache (url, body, fetched_at, status) VALUES (?, ?, ?, ?)",
            (url, body, datetime.now(UTC).isoformat(), status),
        )


def _create_cache_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS http_cache "
        "(url TEXT PRIMARY KEY, body BLOB NOT NULL, fetched_at TEXT NOT NULL, "
        "status INTEGER NOT NULL DEFAULT 200)"
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(http_cache)")}
    if "status" not in columns:
        connection.execute("ALTER TABLE http_cache ADD COLUMN status INTEGER NOT NULL DEFAULT 200")
