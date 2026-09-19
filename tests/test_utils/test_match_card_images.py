"""Регрессии загрузки и ограниченного кэша картинок карточек."""

from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.match_card import images


def _response(data: bytes = b"image", *, status: int = 200) -> MagicMock:
    async def chunks():
        yield data

    response = MagicMock(status=status)
    response.content.iter_chunked.return_value = chunks()
    request = MagicMock()
    request.__aenter__ = AsyncMock(return_value=response)
    request.__aexit__ = AsyncMock(return_value=False)
    return request


@pytest.fixture
def session(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(images, "_cache", OrderedDict())
    monkeypatch.setattr(images, "_get_session", AsyncMock(return_value=session))
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "timeout", "empty", "oversize"])
async def test_failed_download_recovers_without_restart(session, monkeypatch, failure):
    """Временная ошибка не закрепляет заглушку за URL до рестарта."""
    monkeypatch.setattr(images, "_MAX_BYTES", 5)
    failed = _response(b"image", status=503) if failure == "http" else _response(
        b"" if failure == "empty" else b"too-large"
    )
    if failure == "timeout":
        failed.__aenter__.side_effect = TimeoutError()
    session.get.side_effect = [failed, _response()]

    assert await images.fetch_image_bytes("https://example.test/avatar") is None
    assert await images.fetch_image_bytes("https://example.test/avatar") == b"image"
    assert session.get.call_count == 2
    assert await images.fetch_image_bytes("https://example.test/avatar") == b"image"
    assert session.get.call_count == 2


@pytest.mark.asyncio
async def test_cache_evicts_least_recently_used_image(session, monkeypatch):
    """Часто используемая картинка переживает вытеснение старого URL."""
    monkeypatch.setattr(images, "_CACHE_MAX_ENTRIES", 2)
    session.get.side_effect = [_response(b"a"), _response(b"b"), _response(b"c")]
    await images.fetch_image_bytes("a")
    await images.fetch_image_bytes("b")
    assert await images.fetch_image_bytes("a") == b"a"
    await images.fetch_image_bytes("c")
    assert list(images._cache) == ["a", "c"]


@pytest.mark.asyncio
async def test_cache_respects_total_byte_budget(session, monkeypatch):
    """Большие картинки ограничены общим бюджетом, а не только числом URL."""
    monkeypatch.setattr(images, "_CACHE_MAX_BYTES", 5)
    session.get.side_effect = [_response(b"aaa"), _response(b"bbb")]
    await images.fetch_image_bytes("a")
    await images.fetch_image_bytes("b")
    assert dict(images._cache) == {"b": b"bbb"}


@pytest.mark.asyncio
async def test_oversized_response_stops_reading_early(session, monkeypatch):
    """Предел проверяется во время чтения, без загрузки остального тела."""
    monkeypatch.setattr(images, "_MAX_BYTES", 4)
    consumed = []

    async def chunks():
        for chunk in (b"abc", b"de", b"unread"):
            consumed.append(chunk)
            yield chunk

    request = _response()
    request.__aenter__.return_value.content.iter_chunked.return_value = chunks()
    session.get.return_value = request

    assert await images.fetch_image_bytes("large") is None
    assert consumed == [b"abc", b"de"]
    assert "large" not in images._cache
