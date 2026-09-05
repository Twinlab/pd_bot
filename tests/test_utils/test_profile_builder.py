"""Тесты сборщика данных интерактивного профиля."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.activity_data_manager import ActivityDataManager
from utils.cs_links_data_manager import CsLinksDataManager
from utils.links_data_manager import LinksDataManager
from utils.profile.builder import (
    ProfilePeriod,
    ProfileStatsBuilder,
)
from utils.time_utils import MOSCOW_TZ
from utils.top_reactions_data_manager import (
    AuthorLeaderboardEntry,
    LeaderboardEntry,
    TopReactionsDataManager,
)
from utils.user_stats_data_manager import UserStatsDataManager, UserTotals


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        top_reactions=SimpleNamespace(
            ignored_message_ids=[999],
            ignore_self_reactions=True,
        ),
        user_stats=SimpleNamespace(data_since="2024-01-15"),
    )


def _builder() -> tuple[
    ProfileStatsBuilder,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    activity = MagicMock(spec=ActivityDataManager)
    user_stats = MagicMock(spec=UserStatsDataManager)
    reactions = MagicMock(spec=TopReactionsDataManager)
    links = MagicMock(spec=LinksDataManager)
    cs_links = MagicMock(spec=CsLinksDataManager)
    builder = ProfileStatsBuilder(
        activity_manager=activity,
        user_stats_manager=user_stats,
        reactions_manager=reactions,
        links_manager=links,
        cs_links_manager=cs_links,
    )
    return builder, activity, user_stats, reactions, links, cs_links


class TestProfilePeriod:
    """Тесты периода профиля."""

    def test_current_month_uses_moscow_timezone(self) -> None:
        now = datetime(2026, 6, 30, 21, 30, tzinfo=UTC)

        period = ProfilePeriod.current_month(now)

        assert period == ProfilePeriod("month", 2026, 7)
        assert period.label == "Июль 2026"

    @pytest.mark.parametrize(
        "period",
        [
            ("month", 2026, 13),
            ("year", None, None),
            ("year", 2026, 7),
            ("all", 2026, None),
        ],
    )
    def test_rejects_invalid_combinations(
        self,
        period: tuple[str, int | None, int | None],
    ) -> None:
        with pytest.raises(ValueError):
            ProfilePeriod(*period)  # type: ignore[arg-type]


class TestProfileStatsBuilder:
    """Тесты объединения локальных источников профиля."""

    @pytest.mark.asyncio
    async def test_build_stats_merges_daily_data_and_calculates_ranks(self) -> None:
        builder, activity, user_stats, reactions, _, _ = _builder()
        activity.get_monthly_stats = AsyncMock(return_value={"Dota 2": 3600})
        activity.get_daily_stats_by_prefix = AsyncMock(
            return_value={"Dota 2": 600, "Counter-Strike 2": 1200}
        )
        user_stats.get_monthly_totals = AsyncMock(
            return_value={
                1: UserTotals(1, 10, 100),
                2: UserTotals(2, 20, 10),
            }
        )
        user_stats.get_daily_totals_by_prefix = AsyncMock(
            return_value={
                1: UserTotals(1, 5, 50),
                3: UserTotals(3, 100, 1000),
            }
        )
        user_stats.merge_totals.side_effect = UserStatsDataManager.merge_totals
        reactions.get_top_authors = AsyncMock(
            return_value=[
                AuthorLeaderboardEntry(2, 50, 5),
                AuthorLeaderboardEntry(1, 10, 2),
                AuthorLeaderboardEntry(3, 5, 1),
            ]
        )
        period = ProfilePeriod("month", 2026, 7)

        with patch("utils.profile.builder.get_settings", return_value=_settings()):
            stats = await builder.build_stats(
                user_id=1,
                period=period,
                eligible_user_ids={1, 2},
                current_game="Dota 2",
            )

        assert stats.messages == 15
        assert stats.voice_seconds == 150
        assert stats.reactions == 10
        assert stats.top_games == [("Dota 2", 4200), ("Counter-Strike 2", 1200)]
        assert stats.message_rank == 2
        assert stats.voice_rank == 1
        assert stats.reaction_rank == 2
        assert stats.current_game == "Dota 2"
        assert stats.data_since == "2024-01-15"
        activity.get_daily_stats_by_prefix.assert_awaited_once_with(1, "2026-07")
        reactions.get_top_authors.assert_awaited_once_with(
            "month",
            1000,
            year=2026,
            month=7,
            excluded_message_ids={999},
            ignore_self_reactions=True,
            timezone=MOSCOW_TZ,
        )

    @pytest.mark.asyncio
    async def test_build_moments_filters_by_profile_owner(self) -> None:
        builder, _, _, reactions, _, _ = _builder()
        reactions.get_leaderboard = AsyncMock(
            return_value=[
                LeaderboardEntry(
                    message_id=10,
                    channel_id=20,
                    author_id=1,
                    content="Лучший момент",
                    jump_url="https://discord.com/channels/1/20/10",
                    posted_at=datetime(2026, 7, 1, tzinfo=UTC),
                    reactor_count=7,
                    is_historical=False,
                )
            ]
        )
        period = ProfilePeriod("year", 2026)

        with patch("utils.profile.builder.get_settings", return_value=_settings()):
            moments = await builder.build_moments(
                user_id=1, period=period, allowed_channel_ids={20}, limit=3
            )

        assert [(moment.content, moment.reactions) for moment in moments] == [("Лучший момент", 7)]
        reactions.get_leaderboard.assert_awaited_once_with(
            "year",
            3,
            year=2026,
            month=None,
            author_id=1,
            allowed_channel_ids={20},
            excluded_message_ids={999},
            ignore_self_reactions=True,
            timezone=MOSCOW_TZ,
        )

    @pytest.mark.asyncio
    async def test_build_accounts_does_not_call_external_apis(self) -> None:
        builder, _, _, _, links, cs_links = _builder()
        links.get_links = AsyncMock(return_value=[12345])
        cs_links.get_links = AsyncMock(
            return_value=[SimpleNamespace(faceit_player_id="faceit-id", nickname="Player One")]
        )

        accounts = await builder.build_accounts(1)

        assert accounts.dota_ids == (12345,)
        assert accounts.faceit[0].player_id == "faceit-id"
        assert accounts.faceit[0].nickname == "Player One"
