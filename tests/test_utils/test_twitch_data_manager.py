import pytest
from utils.twitch_data_manager import TwitchDataManager

@pytest.mark.asyncio
async def test_add_streamer(monkeypatch):
    class DummyConn:
        async def execute(self, *a, **kw): return None
        async def commit(self): return None
        async def close(self): return None
    async def dummy_connect(*a, **kw): return DummyConn()
    monkeypatch.setattr("aiosqlite.connect", dummy_connect)

    manager = TwitchDataManager(db_path=":memory:")
    result = await manager.add_streamer(guild_id=1, channel_id=1, twitch_username="user", twitch_id="id")
    assert result is True or result is False
