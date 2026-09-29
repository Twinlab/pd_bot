"""Проверки месячных сравнений, номинаций и публичности сообщения месяца."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest

from utils.activity_data_manager import ActivityDataManager
from utils.time_utils import MOSCOW_TZ
from utils.top_reactions_data_manager import (
    AuthorLeaderboardEntry, LeaderboardEntry, TopReactionsDataManager,
)
from utils.user_stats_data_manager import UserStatsDataManager, UserTotals
from utils.wrapped.builder import build_server_wrapped
from utils.wrapped_data_manager import MonthlySnapshot

EMPTY = MonthlySnapshot({}, {})


async def _build(current, previous=EMPTY, *, month=8, year=2026,
                 since="2026-01-01", today=date(2026, 9, 1), reactions=None):
    reactions = reactions or TopReactionsDataManager()
    if not isinstance(reactions.get_leaderboard, AsyncMock):
        reactions.get_leaderboard = AsyncMock(return_value=[])
        reactions.get_top_authors = AsyncMock(return_value=[])
    with (
        patch("utils.wrapped_data_manager.WrappedDataManager.get_month",
              AsyncMock(side_effect=[current, previous])) as read,
        patch("utils.wrapped.monthly.moscow_today", return_value=today),
    ):
        result = await build_server_wrapped(
            scope="monthly", year=year, month=month, stats_mgr=UserStatsDataManager(),
            activity_mgr=ActivityDataManager(), reactions_mgr=reactions, top_limit=5,
            data_since=since, allowed_channel_ids={10}, guild_id=100,
            excluded_message_ids={999}, excluded_user_ids={888},
        )
    return result, read, reactions


async def test_totals_new_nominations_and_previous_month() -> None:
    current = MonthlySnapshot(
        {1: UserTotals(1, 100, 3600), 2: UserTotals(2, 50, 7200)},
        {1: {"A": 3600, "B": 3601}, 3: {"C": 8000, "D": 9000}},
    )
    old = MonthlySnapshot({1: UserTotals(1, 0, 2000)}, {1: {"A": 1000}})
    reactions = TopReactionsDataManager()
    reactions.get_leaderboard = AsyncMock(return_value=[
        LeaderboardEntry(20, 10, 2, "text", "https://untrusted.invalid",
                         datetime(2026, 8, 2, tzinfo=UTC), 47, False)
    ])
    reactions.get_top_authors = AsyncMock(return_value=[
        AuthorLeaderboardEntry(1, 342, 10)
    ])
    result, read, reactions = await _build(current, old, reactions=reactions)
    assert result.total_messages == 150
    assert result.total_voice_seconds == 10800
    assert result.total_game_seconds == 24201
    assert result.active_users == 3
    assert result.previous == {"messages": 0, "voice": 2000, "games": 1000, "users": 1}
    assert result.top_messages[0].user_id == 1
    assert result.top_voice[0].user_id == 2
    nominations = {n.title: n for n in result.nominations}
    assert set(nominations) == {"Разнообразие игр", "Сообщение месяца", "Геймер", "По реакциям"}
    assert nominations["Разнообразие игр"].user_id == 3
    assert nominations["Разнообразие игр"].detail == "2 игры"
    assert result.message_url == "https://discord.com/channels/100/10/20"
    assert read.await_args_list[1].args == (2026, 7)
    for call in (reactions.get_leaderboard.await_args, reactions.get_top_authors.await_args):
        assert call.kwargs["allowed_channel_ids"] == {10}
        assert call.kwargs["excluded_user_ids"] == {888}
        assert call.kwargs["excluded_message_ids"] == {999}
        assert call.kwargs["strict"] is True
        assert call.kwargs["timezone"] is MOSCOW_TZ
        assert call.kwargs["ignore_self_reactions"] is True


@pytest.mark.parametrize("seconds,expected", [(0, False), (3599, False), (3600, False), (3601, True)])
async def test_diversity_strict_hour_boundary(seconds, expected) -> None:
    result, _, _ = await _build(MonthlySnapshot({}, {1: {"A": seconds}}))
    assert any(n.title == "Разнообразие игр" for n in result.nominations) is expected


async def test_ties_are_stable_and_only_five_games() -> None:
    games = {2: {f"Game {i}": 4000 for i in range(7)},
             1: {f"Game {i}": 4000 for i in range(7)}}
    result, _, _ = await _build(MonthlySnapshot({}, games))
    assert result.nominations[0].user_id == 1
    assert len(result.top_games) == 5
    assert result.total_game_seconds == 56000


async def test_empty_month_has_no_invented_winners_or_baseline() -> None:
    result, _, _ = await _build(EMPTY)
    assert result.total_messages == 0
    assert result.nominations == []
    assert result.previous == {}
    assert result.message_url is None


async def test_january_compares_to_previous_year() -> None:
    _, read, _ = await _build(EMPTY, month=1, year=2027, today=date(2027, 2, 1))
    assert read.await_args_list[1].args == (2026, 12)


@pytest.mark.parametrize("since,today", [
    ("2026-07-02", date(2026, 9, 1)),
    (None, date(2026, 9, 1)),
    ("invalid", date(2026, 9, 1)),
    ("2026-01-01", date(2026, 8, 31)),
])
async def test_partial_or_unknown_history_disables_comparison(since, today) -> None:
    result, read, _ = await _build(EMPTY, since=since, today=today)
    assert result.previous == {}
    assert read.await_count == 1


async def test_current_db_error_aborts_report() -> None:
    with pytest.raises(RuntimeError, match="db"):
        await _build(RuntimeError("db"))


async def test_previous_db_error_does_not_become_zero() -> None:
    result, _, _ = await _build(EMPTY, RuntimeError("db"))
    assert result.previous == {}


async def test_reaction_error_aborts_report() -> None:
    reactions = TopReactionsDataManager()
    reactions.get_leaderboard = AsyncMock(side_effect=RuntimeError("reactions"))
    with pytest.raises(RuntimeError, match="reactions"):
        await _build(EMPTY, reactions=reactions)


async def test_future_month_rejected_before_read() -> None:
    with pytest.raises(ValueError):
        await _build(EMPTY, today=date(2026, 7, 1))
