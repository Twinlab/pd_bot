import pytest
from utils.twitch_api import TwitchAPI

@pytest.mark.asyncio
async def test_get_access_token(monkeypatch):
    class DummySession:
        async def post(self, *a, **kw): return DummyResponse()
        async def close(self): return None
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): pass
    class DummyResponse:
        async def json(self): return {"access_token": "token"}
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): pass
    monkeypatch.setattr("aiohttp.ClientSession", lambda: DummySession())
    api = TwitchAPI(client_id="id", client_secret="secret")
    result = await api.get_access_token()
    assert isinstance(result, bool)
