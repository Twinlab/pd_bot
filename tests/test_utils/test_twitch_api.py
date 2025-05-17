from typing import Any

import pytest

from utils.twitch_api import TwitchAPI


@pytest.mark.asyncio
async def test_get_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummySession:
        async def post(self, *a: Any, **kw: Any) -> "DummyResponse":
            return DummyResponse()

        async def close(self) -> None:
            return None

        async def __aenter__(self) -> "DummySession":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            pass

    class DummyResponse:
        async def json(self) -> dict[str, str]:
            return {"access_token": "token"}

        async def __aenter__(self) -> "DummyResponse":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            pass

    monkeypatch.setattr("aiohttp.ClientSession", lambda: DummySession())
    api = TwitchAPI(client_id="id", client_secret="secret")
    result = await api.get_access_token()
    assert isinstance(result, bool)
