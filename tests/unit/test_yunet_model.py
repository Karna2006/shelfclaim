from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from app.capture import yunet_model


@pytest.mark.asyncio
async def test_download_yunet_verifies_hash_before_install(monkeypatch, tmp_path: Path) -> None:
    payload = b"test model bytes"
    expected_hash = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(yunet_model, "MODEL_SHA256", expected_hash)

    async def fake_fetch(url: str, cache_path: Path) -> bytes:
        assert url == yunet_model.MODEL_URL
        assert cache_path == Path("cache/http_cache.sqlite")
        return payload

    monkeypatch.setattr(yunet_model, "fetch_bytes", fake_fetch)
    destination = tmp_path / "models" / "yunet.onnx"

    result = await yunet_model.download_yunet_model(destination)

    assert result == destination
    assert destination.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_yunet_rejects_invalid_hash_without_writing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(yunet_model, "MODEL_SHA256", "0" * 64)

    async def fake_fetch(url: str, cache_path: Path) -> bytes:
        return b"tampered model bytes"

    monkeypatch.setattr(yunet_model, "fetch_bytes", fake_fetch)
    destination = tmp_path / "models" / "yunet.onnx"

    with pytest.raises(ValueError, match="SHA-256"):
        await yunet_model.download_yunet_model(destination)

    assert not destination.exists()
