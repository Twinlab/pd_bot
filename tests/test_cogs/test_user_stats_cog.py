"""Тесты пограничной логики голосовой статистики."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

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
