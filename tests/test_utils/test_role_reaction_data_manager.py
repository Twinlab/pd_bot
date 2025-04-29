import pytest
from utils.role_reaction_data_manager import RoleReactionDataManager

@pytest.fixture
def manager(monkeypatch):
    class DummyConn:
        async def execute(self, *a, **kw): return DummyCursor()
        async def commit(self): return None
        async def close(self): return None
    class DummyCursor:
        async def fetchone(self): return None
        async def fetchall(self): return []
    async def dummy_connect(*a, **kw): return DummyConn()
    monkeypatch.setattr("aiosqlite.connect", dummy_connect)
    return RoleReactionDataManager(db_path=":memory:")

@pytest.mark.asyncio
async def test_get_message_info(manager):
    result = await manager.get_message_info(guild_id=1)
    assert result is None or isinstance(result, tuple)

@pytest.mark.asyncio
async def test_add_role_reaction(manager):
    await manager.add_role_reaction(guild_id=1, channel_id=1, message_id=1, role_id=1, emoji=":)", description="desc")

@pytest.mark.asyncio
async def test_remove_role_reaction(manager):
    result = await manager.remove_role_reaction(guild_id=1, emoji=":)")
    assert isinstance(result, bool)

@pytest.mark.asyncio
async def test_get_all_role_reactions(manager):
    result = await manager.get_all_role_reactions(guild_id=1)
    assert isinstance(result, list)

@pytest.mark.asyncio
async def test_get_role_by_emoji(manager):
    result = await manager.get_role_by_emoji(guild_id=1, emoji=":)")
    assert result is None or isinstance(result, int)

@pytest.mark.asyncio
async def test_update_message_content(manager):
    result = await manager.update_message_content(guild_id=1, message_content="test")
    assert isinstance(result, bool)
