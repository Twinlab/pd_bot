from datetime import date

import pytest

from utils.activity_data_manager import ActivityDataManager


@pytest.fixture
def manager(monkeypatch) -> ActivityDataManager:
    class DummyConn:
        async def execute(self, *a, **kw):
            return DummyCursor()

        async def commit(self):
            return None

        async def close(self):
            return None

        # Добавляем методы для асинхронного контекстного менеджера
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    class DummyCursor:
        async def fetchone(self):
            return None

        async def fetchall(self):
            return []

    # Создаем правильный асинхронный мок для connect
    async def dummy_connect(*a, **kw):
        return DummyConn()

    monkeypatch.setattr("aiosqlite.connect", dummy_connect)
    return ActivityDataManager(db_path=":memory:")


@pytest.mark.asyncio
async def test_update_activity(manager: ActivityDataManager) -> None:
    await manager.update_activity(1, "game", 10)


@pytest.mark.asyncio
async def test_get_daily_stats(manager: ActivityDataManager) -> None:
    result = await manager.get_daily_stats(target_date=date.today())
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_transfer_daily_to_monthly(manager: ActivityDataManager) -> None:
    result = await manager.transfer_daily_to_monthly(target_date=date.today())
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_get_monthly_stats(manager: ActivityDataManager) -> None:
    result = await manager.get_monthly_stats(user_id=1, year=2024, month=4)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_aggregated_monthly_stats(manager: ActivityDataManager) -> None:
    result = await manager.get_aggregated_monthly_stats(year=2024, month=4)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_all_time_stats(manager: ActivityDataManager) -> None:
    result = await manager.get_all_time_stats(user_id=1)
    assert isinstance(result, dict)
