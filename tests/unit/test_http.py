from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from app.net.http import fetch_bytes


@pytest.mark.asyncio
async def test_fetch_bytes_caches_response_and_sets_user_agent(tmp_path: Path) -> None:
    url = "https://models.example.test/yunet.onnx"
    cache_path = tmp_path / "cache.sqlite"
    with respx.mock(assert_all_called=True) as router:
        route = router.get(url).mock(return_value=httpx.Response(200, content=b"model"))

        first = await fetch_bytes(url, cache_path)
        second = await fetch_bytes(url, cache_path)

    assert first == second == b"model"
    assert route.call_count == 1
    assert route.calls[0].request.headers["user-agent"].startswith("ShelfClaim/")


@pytest.mark.asyncio
async def test_fetch_bytes_allows_one_configured_connection_retry(tmp_path: Path) -> None:
    url = "https://books.example.test/search"
    with respx.mock(assert_all_called=True) as router:
        route = router.get(url).mock(
            side_effect=[
                httpx.ConnectError("first connection failed"),
                httpx.ConnectError("second connection failed"),
            ]
        )

        with pytest.raises(httpx.ConnectError):
            await fetch_bytes(url, tmp_path / "cache.sqlite", timeout_s=5, max_retries=1)

    assert route.call_count == 2


@pytest.mark.asyncio
async def test_fetch_bytes_caches_http_errors_when_replay_determinism_is_requested(
    tmp_path: Path,
) -> None:
    url = "https://books.example.test/search?q=visible"
    events = []
    with respx.mock(assert_all_called=True) as router:
        route = router.get(url).mock(return_value=httpx.Response(429, content=b"quota"))

        for _ in range(2):
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_bytes(
                    url,
                    tmp_path / "cache.sqlite",
                    cache_ttl=None,
                    cache_http_errors=True,
                    on_request=lambda request_url, status, cached, error: events.append(
                        (request_url, status, cached, error)
                    ),
                )

    assert route.call_count == 1
    assert events == [
        (url, 429, False, None),
        (url, 429, True, "cached_http_status"),
    ]
