import pytest
from utils.activity_data_manager import ActivityDataManager

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
    return ActivityDataManager(db_path=":memory:")

@pytest.mark.asyncio
async def test_update_activity(manager):
    await manager.update_activity(1, "game", 10)

from datetime import date

@pytest.mark.asyncio
async def test_get_daily_stats(manager):
    result = await manager.get_daily_stats(target_date=date.today())
    assert isinstance(result, dict)

@pytest.mark.asyncio
async def test_transfer_daily_to_monthly(manager):
    result = await manager.transfer_daily_to_monthly(target_date=date.today())
    assert isinstance(result, bool)

@pytest.mark.asyncio
async def test_get_monthly_stats(manager):
    result = await manager.get_monthly_stats(user_id=1, year=2024, month=4)
    assert isinstance(result, dict)

@pytest.mark.asyncio
async def test_get_aggregated_monthly_stats(manager):
    result = await manager.get_aggregated_monthly_stats(year=2024, month=4)
    assert isinstance(result, dict)

@pytest.mark.asyncio
async def test_get_all_time_stats(manager):
    result = await manager.get_all_time_stats(user_id=1)
    assert isinstance(result, dict)

@pytest.mark.asyncio
async def test_migrate_links_from_json(manager):
    await manager.migrate_links_from_json(json_file_path="fake.json")

@pytest.mark.asyncio
async def test_migrate_activity_from_json(manager):
    await manager.migrate_activity_from_json()
