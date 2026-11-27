"""Fetch Google Shopping, eBay and FX responses through cached HTTP.

Input: exact book query and locale configuration. Output: provider JSON plus
the raw payload, which callers save under the sweep evidence folder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode

from app.net.http import fetch_bytes
from app.settings import Settings


@dataclass(frozen=True)
class SearchPayload:
    data: dict[str, object]
    raw: bytes
    request_url: str


class SerpApiProvider:
    """Issue one SerpAPI search at a time; the caller enforces run limits."""

    def __init__(self, settings: Settings) -> None:
        if settings.serpapi_api_key is None:
            raise ValueError("SERPAPI_API_KEY is required for repricing")
        self._key = settings.serpapi_api_key.get_secret_value()
        self._cache = settings.cache_db
        self.query_log: list[dict[str, object]] = []

    async def shopping(self, query: str, locale: dict[str, object]) -> SearchPayload:
        params = {
            "engine": "google_shopping",
            "q": query,
            "gl": str(locale["gl"]),
            "hl": str(locale["hl"]),
            "google_domain": str(locale["google_domain"]),
            "api_key": self._key,
        }
        return await self._get("https://serpapi.com/search.json", params)

    async def ebay(self, query: str, domain: str) -> SearchPayload:
        params = {
            "engine": "ebay",
            "_nkw": query,
            "ebay_domain": domain,
            "api_key": self._key,
        }
        return await self._get("https://serpapi.com/search.json", params)

    async def fx(self, from_currency: str, to_currency: str) -> SearchPayload:
        query = urlencode({"base": from_currency, "symbols": to_currency})
        url = f"https://api.frankfurter.dev/v1/latest?{query}"
        safe_url = url

        def observe(_url: str, status: int | None, cached: bool, error: str | None) -> None:
            self.query_log.append(
                {"url": safe_url, "status": status, "cache": cached, "error": error}
            )

        raw = await fetch_bytes(
            url,
            self._cache,
            on_request=observe,
            cache_ttl=None,
            cache_http_errors=True,
        )
        data = json.loads(raw)
        return SearchPayload(data=data, raw=raw, request_url=url)

    async def _get(self, base: str, params: dict[str, str]) -> SearchPayload:
        url = f"{base}?{urlencode(params)}"
        safe_params = {**params, "api_key": "REDACTED"}
        safe_url = f"{base}?{urlencode(safe_params)}"

        def observe(_url: str, status: int | None, cached: bool, error: str | None) -> None:
            self.query_log.append(
                {"url": safe_url, "status": status, "cache": cached, "error": error}
            )

        raw = await fetch_bytes(
            url,
            self._cache,
            cache_key=safe_url,
            on_request=observe,
            cache_ttl=None,
            cache_http_errors=True,
        )
        data = json.loads(raw)
        return SearchPayload(data=data, raw=raw, request_url=safe_url)
