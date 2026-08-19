"""Тесты пограничной логики голосовой статистики."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.user_stats import UserStatsTracker


@pytest.mark.asyncio
async def test_save_voice_interval_splits_moscow_midnight() -> None:
    """Голосовые секунды по обе стороны полуночи записываются в разные даты."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker.stats_manager = MagicMock()
    tracker.stats_manager.add_voice_seconds = AsyncMock()

    await tracker._save_voice_interval(
        123,
        datetime(2026, 7, 23, 20, 59, 58, tzinfo=UTC),
        datetime(2026, 7, 23, 21, 0, 3, tzinfo=UTC),
    )

    assert tracker.stats_manager.add_voice_seconds.await_args_list == [
        ((123, 2), {"target_date": date(2026, 7, 23)}),
        ((123, 3), {"target_date": date(2026, 7, 24)}),
    ]


@pytest.mark.asyncio
async def test_flush_active_serializes_concurrent_jobs() -> None:
    """Полуночный и периодический flush не учитывают один голосовой интервал дважды."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker._voice_lock = asyncio.Lock()
    tracker.bot = MagicMock()
    tracker.bot.guilds = []
    tracker.stats_manager = MagicMock()
    write_started = asyncio.Event()
    allow_write = asyncio.Event()

    async def slow_write(*args, **kwargs) -> None:
        write_started.set()
        await allow_write.wait()

    tracker.stats_manager.add_voice_seconds = AsyncMock(side_effect=slow_write)
    first_now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    tracker.voice_sessions = {123: first_now - timedelta(minutes=2)}

    with patch("cogs.user_stats.datetime") as mock_datetime:
        mock_datetime.now.return_value = first_now
        first_flush = asyncio.create_task(tracker._flush_active(restart=True))
        await write_started.wait()
        second_flush = asyncio.create_task(tracker._flush_active(restart=True))
        await asyncio.sleep(0)
        allow_write.set()
        await asyncio.gather(first_flush, second_flush)

    tracker.stats_manager.add_voice_seconds.assert_awaited_once()
    assert tracker.voice_sessions == {}


@pytest.mark.asyncio
async def test_daily_transfer_processes_stale_dates() -> None:
    """После простоя переносит в месяцы все старые дневные user-stats."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker._voice_lock = asyncio.Lock()
    tracker.voice_sessions = {}
    tracker.stats_manager = MagicMock()
    tracker.stats_manager.get_pending_daily_dates = AsyncMock(
        return_value=[date(2026, 8, 17), date(2026, 8, 18)]
    )
    tracker.stats_manager.transfer_daily_to_monthly = AsyncMock(return_value=True)

    with patch("cogs.user_stats.moscow_today", return_value=date(2026, 8, 20)):
        await UserStatsTracker.daily_transfer.coro(tracker)

    tracker.stats_manager.get_pending_daily_dates.assert_awaited_once_with(date(2026, 8, 20))
    transferred_dates = [
        call.args[0]
        for call in tracker.stats_manager.transfer_daily_to_monthly.await_args_list
    ]
    assert transferred_dates == [date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)]
