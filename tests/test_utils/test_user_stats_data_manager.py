"""Тесты менеджера статистики сообщений/голоса."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.user_stats_data_manager import UserStatsDataManager, UserTotals


class _AwaitableRows:
    """Имитация Tortoise queryset: возвращает список строк при ``await``."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def __await__(self):
        async def _coro() -> list[object]:
            return self._rows

        return _coro().__await__()


@pytest.fixture
def manager():
    return UserStatsDataManager()


class TestStaticHelpers:
    """Тесты чистых статических методов."""

    def test_merge_totals(self):
        a = {1: UserTotals(1, 10, 100), 2: UserTotals(2, 5, 0)}
        b = {1: UserTotals(1, 3, 50), 3: UserTotals(3, 0, 200)}
        merged = UserStatsDataManager.merge_totals(a, b)
        assert merged[1].messages == 13
        assert merged[1].voice_seconds == 150
        assert merged[2].messages == 5
        assert merged[3].voice_seconds == 200

    def test_top_by_messages(self):
        totals = {
            1: UserTotals(1, 10, 0),
            2: UserTotals(2, 50, 0),
            3: UserTotals(3, 0, 100),
        }
        top = UserStatsDataManager.top_by_messages(totals, 2)
        assert [t.user_id for t in top] == [2, 1]

    def test_top_by_voice(self):
        totals = {
            1: UserTotals(1, 0, 30),
            2: UserTotals(2, 0, 90),
            3: UserTotals(3, 5, 0),
        }
        top = UserStatsDataManager.top_by_voice(totals, 5)
        assert [t.user_id for t in top] == [2, 1]


class TestIncrement:
    """Тесты атомарного инкремента дневной строки."""

    @pytest.mark.asyncio
    async def test_add_message_updates_existing(self, manager):
        with patch("utils.user_stats_data_manager.DailyUserStats.filter") as mock_filter:
            mock_filter.return_value.update = AsyncMock(return_value=1)
            with patch(
                "utils.user_stats_data_manager.DailyUserStats.create", new_callable=AsyncMock
            ) as mock_create:
                await manager.add_message(123)
                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_voice_creates_when_missing(self, manager):
        with patch("utils.user_stats_data_manager.DailyUserStats.filter") as mock_filter:
            mock_filter.return_value.update = AsyncMock(return_value=0)
            with patch(
                "utils.user_stats_data_manager.DailyUserStats.create", new_callable=AsyncMock
            ) as mock_create:
                await manager.add_voice_seconds(123, 300)
                mock_create.assert_called_once()
                _, kwargs = mock_create.call_args
                assert kwargs["voice_seconds"] == 300
                assert kwargs["messages"] == 0

    @pytest.mark.asyncio
    async def test_add_voice_uses_explicit_date(self, manager):
        """Голосовые секунды записываются в переданную календарную дату."""
        with patch("utils.user_stats_data_manager.DailyUserStats.filter") as mock_filter:
            mock_filter.return_value.update = AsyncMock(return_value=1)

            await manager.add_voice_seconds(
                123,
                300,
                target_date=date(2026, 7, 23),
            )

        assert mock_filter.call_args.kwargs["date"] == "2026-07-23"

    @pytest.mark.asyncio
    async def test_zero_delta_noop(self, manager):
        with patch("utils.user_stats_data_manager.DailyUserStats.filter") as mock_filter:
            await manager.add_voice_seconds(123, 0)
            mock_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_database_error_is_not_silenced(self, manager):
        """Счётчик сообщает об ошибке, чтобы голосовая сессия могла быть повторена."""
        with patch(
            "utils.user_stats_data_manager.DailyUserStats.filter",
            side_effect=RuntimeError("db unavailable"),
        ):
            with pytest.raises(RuntimeError, match="db unavailable"):
                await manager.add_voice_seconds(123, 300)


class TestPendingDailyDates:
    """Тесты поиска дневных строк, оставшихся после простоя бота."""

    @pytest.mark.asyncio
    async def test_returns_sorted_unique_valid_dates(self, manager):
        query = MagicMock()
        query.distinct.return_value.values_list = AsyncMock(
            return_value=["2026-08-19", "invalid", "2026-08-17", "2026-08-19"]
        )

        with patch(
            "utils.user_stats_data_manager.DailyUserStats.filter", return_value=query
        ) as mock_filter:
            result = await manager.get_pending_daily_dates(date(2026, 8, 20))

        mock_filter.assert_called_once_with(date__lt="2026-08-20")
        assert result == [date(2026, 8, 17), date(2026, 8, 19)]

    @pytest.mark.asyncio
    async def test_database_error_returns_empty_list(self, manager):
        with patch(
            "utils.user_stats_data_manager.DailyUserStats.filter",
            side_effect=RuntimeError("db unavailable"),
        ):
            assert await manager.get_pending_daily_dates(date(2026, 8, 20)) == []


class TestUserMonthly:
    """Тесты выборки тоталов одного пользователя за месяц."""

    @pytest.mark.asyncio
    async def test_sums_monthly_rows(self, manager):
        rows = [
            SimpleNamespace(messages=10, voice_seconds=120),
            SimpleNamespace(messages=5, voice_seconds=80),
        ]
        with patch(
            "utils.user_stats_data_manager.MonthlyUserStats.filter",
            return_value=_AwaitableRows(rows),
        ):
            totals = await manager.get_user_monthly(123, 2026, 5)
        assert totals == UserTotals(user_id=123, messages=15, voice_seconds=200)

    @pytest.mark.asyncio
    async def test_no_data_returns_zero(self, manager):
        with patch(
            "utils.user_stats_data_manager.MonthlyUserStats.filter",
            return_value=_AwaitableRows([]),
        ):
            totals = await manager.get_user_monthly(999, 2026, 5)
        assert totals == UserTotals(user_id=999, messages=0, voice_seconds=0)


class TestAllTimeTotals:
    """Тесты полного периода профиля."""

    @pytest.mark.asyncio
    async def test_merges_monthly_and_untransferred_daily_rows(self, manager):
        monthly_query = MagicMock()
        monthly_query.group_by.return_value.annotate.return_value.values.return_value = (
            _AwaitableRows(
                [
                    {
                        "discord_user_id": 1,
                        "total_messages": 10,
                        "total_voice": 100,
                    }
                ]
            )
        )
        daily_query = MagicMock()
        daily_query.group_by.return_value.annotate.return_value.values.return_value = (
            _AwaitableRows(
                [
                    {
                        "discord_user_id": 1,
                        "total_messages": 5,
                        "total_voice": 50,
                    },
                    {
                        "discord_user_id": 2,
                        "total_messages": 2,
                        "total_voice": 0,
                    },
                ]
            )
        )

        with (
            patch(
                "utils.user_stats_data_manager.MonthlyUserStats.all",
                return_value=monthly_query,
            ),
            patch(
                "utils.user_stats_data_manager.DailyUserStats.all",
                return_value=daily_query,
            ),
        ):
            totals = await manager.get_all_time_totals()

        assert totals == {
            1: UserTotals(1, 15, 150),
            2: UserTotals(2, 2, 0),
        }
