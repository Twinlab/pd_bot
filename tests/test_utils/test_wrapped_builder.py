"""Тесты сборщика wrapped-данных."""

from unittest.mock import AsyncMock

import pytest

from utils.activity_data_manager import ActivityDataManager
from utils.top_reactions_data_manager import AuthorLeaderboardEntry, TopReactionsDataManager
from utils.user_stats_data_manager import UserStatsDataManager, UserTotals
from utils.wrapped.builder import build_server_wrapped


@pytest.mark.asyncio
async def test_build_server_wrapped_monthly():
    stats = UserStatsDataManager()
    stats.get_monthly_totals = AsyncMock(
        return_value={
            1: UserTotals(1, messages=100, voice_seconds=3600),
            2: UserTotals(2, messages=50, voice_seconds=7200),
        }
    )
    stats.get_daily_totals_by_prefix = AsyncMock(return_value={})

    activity = ActivityDataManager()
    activity.get_aggregated_monthly_stats = AsyncMock(
        return_value={1: {"Dota 2": 3600}, 3: {"CS2": 1800}}
    )

    reactions = TopReactionsDataManager()
    reactions.get_top_authors = AsyncMock(
        return_value=[AuthorLeaderboardEntry(author_id=2, total_reactions=42, message_count=5)]
    )

    summary = await build_server_wrapped(
        scope="monthly",
        year=2026,
        month=5,
        stats_mgr=stats,
        activity_mgr=activity,
        reactions_mgr=reactions,
        top_limit=5,
    )

    assert summary.period_label == "Май 2026"
    assert summary.total_messages == 150
    assert summary.total_voice_seconds == 10800
    assert summary.total_game_seconds == 5400
    assert summary.active_users == 3

    assert summary.top_messages[0].user_id == 1
    assert summary.top_voice[0].user_id == 2

    noms = {n.title: n.user_id for n in summary.nominations}
    assert noms["Топ по сообщениям"] == 1
    assert noms["Топ по войсу"] == 2
    assert noms["Топ-геймер"] == 1
    assert noms["Топ по полученным реакциям"] == 2


@pytest.mark.asyncio
async def test_build_server_wrapped_empty():
    stats = UserStatsDataManager()
    stats.get_monthly_totals = AsyncMock(return_value={})
    stats.get_daily_totals_by_prefix = AsyncMock(return_value={})

    activity = ActivityDataManager()
    activity.get_aggregated_monthly_stats = AsyncMock(return_value={})

    reactions = TopReactionsDataManager()
    reactions.get_top_authors = AsyncMock(return_value=[])

    summary = await build_server_wrapped(
        scope="monthly",
        year=2026,
        month=1,
        stats_mgr=stats,
        activity_mgr=activity,
        reactions_mgr=reactions,
        top_limit=5,
    )

    assert summary.total_messages == 0
    assert summary.active_users == 0
    assert summary.nominations == []
