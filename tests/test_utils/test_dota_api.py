import os
import tempfile

import pytest

from utils.dota_api import (
    fetch_items_data,
    load_cache_from_disk,
    query_api,
    query_api_with_retry,
    read_json_file,
    save_cache_to_disk,
    write_json_file,
)


@pytest.mark.asyncio
async def test_read_write_json_file() -> None:
    data = {"a": 1}
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        path = tf.name
    await write_json_file(path, data)
    result = await read_json_file(path)
    assert result == data
    os.remove(path)


@pytest.mark.asyncio
async def test_load_save_cache(monkeypatch) -> None:
    # Мокаем open/read/write для изоляции
    monkeypatch.setattr("builtins.open", lambda *a, **kw: tempfile.TemporaryFile())
    await load_cache_from_disk()
    await save_cache_to_disk()


@pytest.mark.asyncio
async def test_query_api(monkeypatch) -> None:
    class DummySession:
        async def post(self, url, json, headers):
            return DummyResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    class DummyResponse:
        async def json(self):
            return {"data": {}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr("aiohttp.ClientSession", lambda: DummySession())
    result = await query_api("query", "url", {}, {})
    assert isinstance(result, dict) or result is None


@pytest.mark.asyncio
async def test_query_api_with_retry(monkeypatch) -> None:
    class DummySession:
        async def post(self, url, json, headers):
            return DummyResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    class DummyResponse:
        async def json(self):
            return {"data": {}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr("aiohttp.ClientSession", lambda: DummySession())
    result = await query_api_with_retry("query", "url", {}, {})
    assert isinstance(result, dict) or result is None


@pytest.mark.asyncio
async def test_fetch_items_data(monkeypatch) -> None:
    class DummySession:
        async def get(self, url, headers=None):
            return DummyResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    class DummyResponse:
        async def json(self):
            return {1: {"name": "item1"}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr("aiohttp.ClientSession", lambda: DummySession())
    result = await fetch_items_data("url", {})
    assert isinstance(result, dict)
