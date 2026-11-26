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
