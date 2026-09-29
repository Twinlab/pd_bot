"""Снимок wrapped проверяется на SQLite, включая перенос дневных записей."""

from collections.abc import AsyncIterator
from datetime import date
from unittest.mock import patch

import pytest
from tortoise import Tortoise

from utils.activity_data_manager import ActivityDataManager
from utils.models import DailyActivity, DailyUserStats, MonthlyActivity, MonthlyUserStats
from utils.user_stats_data_manager import UserStatsDataManager
from utils.wrapped_data_manager import WrappedDataManager


@pytest.fixture
async def db() -> AsyncIterator[None]:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["utils.models"]})
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


async def test_monthly_and_daily_snapshot_stays_same_after_transfer(db) -> None:
    await MonthlyUserStats.create(discord_user_id=1, year=2026, month=8,
                                  messages=100, voice_seconds=3600)
    await DailyUserStats.create(discord_user_id=1, date="2026-08-31",
                                messages=20, voice_seconds=60)
    await MonthlyActivity.create(discord_user_id=1, game_name="A", year=2026,
                                 month=8, total_seconds_in_month=1800)
    await DailyActivity.create(discord_user_id=1, game_name="A", date="2026-08-31",
                               seconds_played_today=1801)
    await DailyActivity.create(discord_user_id=9, game_name="B", date="2026-09-01",
                               seconds_played_today=9000)
    manager = WrappedDataManager()
    before = await manager.get_month(2026, 8)
    assert before.users[1].messages == 120
    assert before.users[1].voice_seconds == 3660
    assert before.games == {1: {"A": 3601}}
    assert await UserStatsDataManager().transfer_daily_to_monthly(date(2026, 8, 31))
    assert await ActivityDataManager().transfer_daily_to_monthly(date(2026, 8, 31))
    assert await manager.get_month(2026, 8) == before


async def test_empty_month_is_successful_empty_snapshot(db) -> None:
    snapshot = await WrappedDataManager().get_month(2026, 1)
    assert snapshot.users == snapshot.games == {}


async def test_read_error_propagates(db) -> None:
    with patch("utils.wrapped_data_manager.DailyUserStats.filter",
               side_effect=RuntimeError("read failed")):
        with pytest.raises(RuntimeError, match="read failed"):
            await WrappedDataManager().get_month(2026, 8)


async def test_negative_counter_rejected(db) -> None:
    await MonthlyUserStats.create(discord_user_id=1, year=2026, month=8,
                                  messages=-1, voice_seconds=0)
    with pytest.raises(ValueError):
        await WrappedDataManager().get_month(2026, 8)


async def test_invalid_period_rejected() -> None:
    with pytest.raises(ValueError):
        await WrappedDataManager().get_month(2026, 13)
