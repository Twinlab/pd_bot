"""Тесты для модуля управления данными активности пользователей."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.activity_data_manager import ActivityDataManager


@pytest.fixture
def manager():
    """Создает экземпляр ActivityDataManager."""
    return ActivityDataManager()


class TestActivityDataManagerInit:
    """Тесты инициализации ActivityDataManager."""

    def test_init(self):
        """Тест инициализации."""
        manager = ActivityDataManager()
        assert manager is not None


class TestUpdateActivity:
    """Тесты метода update_activity."""

    @pytest.mark.asyncio
    async def test_update_activity_success_create(self, manager):
        """Тест успешного создания новой записи активности."""
        # Мокаем filter().update() чтобы он вернул 0 (запись не найдена)
        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            mock_filter.return_value.update = AsyncMock(return_value=0)

            with patch(
                "utils.activity_data_manager.DailyActivity.create", new_callable=AsyncMock
            ) as mock_create:
                await manager.update_activity(123, "Dota 2", 3600)

                mock_filter.assert_called_once()
                mock_create.assert_called_once()
                args, kwargs = mock_create.call_args
                assert kwargs["discord_user_id"] == 123
                assert kwargs["game_name"] == "Dota 2"
                assert kwargs["seconds_played_today"] == 3600

    @pytest.mark.asyncio
    async def test_update_activity_success_update(self, manager):
        """Тест успешного обновления существующей записи активности."""
        # Мокаем filter().update() чтобы он вернул 1 (запись обновлена)
        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            mock_filter.return_value.update = AsyncMock(return_value=1)

            with patch(
                "utils.activity_data_manager.DailyActivity.create", new_callable=AsyncMock
            ) as mock_create:
                await manager.update_activity(123, "Dota 2", 3600)

                mock_filter.assert_called_once()
                mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_activity_uses_explicit_date(self, manager):
        """Переданная дата используется вместо даты запуска процесса."""
        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            mock_filter.return_value.update = AsyncMock(return_value=1)

            await manager.update_activity(
                123,
                "Dota 2",
                120,
                target_date=date(2026, 7, 23),
            )

        assert mock_filter.call_args.kwargs["date"] == "2026-07-23"

    @pytest.mark.asyncio
    async def test_update_activity_zero_seconds(self, manager):
        """Тест обновления активности с нулевым временем."""
        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            await manager.update_activity(123, "Dota 2", 0)
            mock_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_activity_negative_seconds(self, manager):
        """Тест обновления активности с отрицательным временем."""
        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            await manager.update_activity(123, "Dota 2", -100)
            mock_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_activity_database_error(self, manager):
        """Тест обработки ошибки базы данных при обновлении активности."""
        with patch(
            "utils.activity_data_manager.DailyActivity.filter",
            side_effect=Exception("Database error"),
        ):
            # Не должно выбрасывать исключение, а логировать ошибку
            await manager.update_activity(123, "Dota 2", 3600)

    @pytest.mark.asyncio
    async def test_update_activity_race_condition_recovers(self, manager):
        """Тест восстановления после race condition между update→0 и create().

        Имитируем ситуацию: первый update вернул 0 (записи нет), но между ним
        и нашим create() параллельный вызов успел создать запись — наш create()
        падает на IntegrityError. Менеджер должен повторить update, чтобы наша
        дельта секунд не потерялась.
        """
        from tortoise.exceptions import IntegrityError

        first_update = AsyncMock(return_value=0)  # сначала записи не было
        retry_update = AsyncMock(return_value=1)  # после конфликта повторный update
        # filter() вызывается дважды: первый раз — попытка update,
        # второй раз — повторный update после IntegrityError.
        filter_mock = MagicMock()
        filter_mock.side_effect = [
            MagicMock(update=first_update),
            MagicMock(update=retry_update),
        ]

        with (
            patch("utils.activity_data_manager.DailyActivity.filter", filter_mock),
            patch(
                "utils.activity_data_manager.DailyActivity.create",
                new_callable=AsyncMock,
                side_effect=IntegrityError("UNIQUE constraint failed"),
            ) as mock_create,
        ):
            await manager.update_activity(123, "Dota 2", 3600)

            # Первый update попытался прибавить дельту, но строки не было.
            first_update.assert_awaited_once()
            # Create упал из-за race condition.
            mock_create.assert_awaited_once()
            # После IntegrityError повторный update сработал и прибавил секунды.
            retry_update.assert_awaited_once()


class TestGetDailyStats:
    """Тесты метода get_daily_stats."""

    @pytest.mark.asyncio
    async def test_get_daily_stats_success(self, manager):
        """Тест успешного получения дневной статистики."""
        mock_activity1 = MagicMock(
            discord_user_id=123, game_name="Dota 2", seconds_played_today=3600
        )
        mock_activity2 = MagicMock(
            discord_user_id=123, game_name="CS:GO", seconds_played_today=1800
        )
        mock_activity3 = MagicMock(
            discord_user_id=456, game_name="Dota 2", seconds_played_today=7200
        )

        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            # Имитируем awaitable результат filter()
            future = asyncio.Future()
            future.set_result([mock_activity1, mock_activity2, mock_activity3])
            mock_filter.return_value = future

            target_date = date(2024, 5, 26)
            result = await manager.get_daily_stats(target_date)

            expected = {123: {"Dota 2": 3600, "CS:GO": 1800}, 456: {"Dota 2": 7200}}
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_daily_stats_empty_result(self, manager):
        """Тест получения дневной статистики без данных."""
        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            future = asyncio.Future()
            future.set_result([])
            mock_filter.return_value = future

            target_date = date(2024, 5, 26)
            result = await manager.get_daily_stats(target_date)

            assert result == {}

    @pytest.mark.asyncio
    async def test_get_daily_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении дневной статистики."""
        with patch(
            "utils.activity_data_manager.DailyActivity.filter",
            side_effect=Exception("Database error"),
        ):
            target_date = date(2024, 5, 26)
            result = await manager.get_daily_stats(target_date)
            assert result == {}


class TestGetPendingDailyDates:
    """Тесты получения неархивированных дат."""

    @pytest.mark.asyncio
    async def test_returns_sorted_unique_dates(self, manager):
        """Возвращает старые даты в хронологическом порядке без дублей."""
        queryset = MagicMock()
        queryset.distinct.return_value.values_list = AsyncMock(
            return_value=["2025-05-01", "2025-04-29", "2025-05-01"]
        )

        with patch(
            "utils.activity_data_manager.DailyActivity.filter",
            return_value=queryset,
        ) as mock_filter:
            result = await manager.get_pending_daily_dates(date(2025, 5, 2))

        assert result == [date(2025, 4, 29), date(2025, 5, 1)]
        mock_filter.assert_called_once_with(date__lt="2025-05-02")
        queryset.distinct.assert_called_once_with()
        queryset.distinct.return_value.values_list.assert_awaited_once_with("date", flat=True)

    @pytest.mark.asyncio
    async def test_skips_invalid_dates(self, manager):
        """Повреждённая дата не блокирует архивацию корректных записей."""
        queryset = MagicMock()
        queryset.distinct.return_value.values_list = AsyncMock(
            return_value=["not-a-date", "2025-05-01"]
        )

        with patch(
            "utils.activity_data_manager.DailyActivity.filter",
            return_value=queryset,
        ):
            result = await manager.get_pending_daily_dates(date(2025, 5, 2))

        assert result == [date(2025, 5, 1)]

    @pytest.mark.asyncio
    async def test_database_error_returns_empty_list(self, manager):
        """Ошибка чтения не мешает обработать как минимум вчерашний день."""
        with patch(
            "utils.activity_data_manager.DailyActivity.filter",
            side_effect=Exception("Database error"),
        ):
            result = await manager.get_pending_daily_dates(date(2025, 5, 2))

        assert result == []


class TestTransferDailyToMonthly:
    """Тесты метода transfer_daily_to_monthly."""

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_success(self, manager):
        """Тест успешного переноса дневных данных в месячные (создание новой записи)."""
        mock_daily_record = MagicMock(
            discord_user_id=123, game_name="Dota 2", seconds_played_today=3600
        )

        # Мокаем транзакцию
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()

        with patch("tortoise.transactions.in_transaction", return_value=mock_transaction):
            with patch("utils.activity_data_manager.DailyActivity.filter") as mock_daily_filter:
                mock_daily_queryset = MagicMock()
                mock_daily_queryset.all = AsyncMock(return_value=[mock_daily_record])
                mock_daily_queryset.delete = AsyncMock()
                mock_daily_filter.return_value = mock_daily_queryset

                with (
                    patch(
                        "utils.activity_data_manager.MonthlyActivity.filter"
                    ) as mock_monthly_filter,
                    patch(
                        "utils.activity_data_manager.MonthlyActivity.bulk_create",
                        new_callable=AsyncMock,
                    ) as mock_bulk_create,
                ):
                    # Существующих записей нет — будет INSERT.
                    mock_monthly_filter.return_value.all = AsyncMock(return_value=[])
                    mock_monthly_filter.return_value.update = AsyncMock(return_value=0)

                    target_date = date(2024, 5, 26)
                    result = await manager.transfer_daily_to_monthly(target_date)

                    assert result is True
                    mock_bulk_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_update_existing(self, manager):
        """Тест обновления существующей месячной записи."""
        mock_daily_record = MagicMock(
            discord_user_id=123, game_name="Dota 2", seconds_played_today=3600
        )

        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()

        existing_monthly = MagicMock(discord_user_id=123, game_name="Dota 2")

        with patch("tortoise.transactions.in_transaction", return_value=mock_transaction):
            with patch("utils.activity_data_manager.DailyActivity.filter") as mock_daily_filter:
                mock_daily_queryset = MagicMock()
                mock_daily_queryset.all = AsyncMock(return_value=[mock_daily_record])
                mock_daily_queryset.delete = AsyncMock()
                mock_daily_filter.return_value = mock_daily_queryset

                with (
                    patch(
                        "utils.activity_data_manager.MonthlyActivity.filter"
                    ) as mock_monthly_filter,
                    patch(
                        "utils.activity_data_manager.MonthlyActivity.bulk_create",
                        new_callable=AsyncMock,
                    ) as mock_bulk_create,
                ):
                    # Существующая запись уже есть — будет UPDATE, не INSERT.
                    mock_monthly_filter.return_value.all = AsyncMock(
                        return_value=[existing_monthly]
                    )
                    mock_monthly_filter.return_value.update = AsyncMock(return_value=1)

                    target_date = date(2024, 5, 26)
                    result = await manager.transfer_daily_to_monthly(target_date)

                    assert result is True
                    mock_bulk_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_error(self, manager):
        """Тест обработки ошибки при переносе."""
        with patch(
            "tortoise.transactions.in_transaction", side_effect=Exception("Transaction error")
        ):
            target_date = date(2024, 5, 26)
            result = await manager.transfer_daily_to_monthly(target_date)
            assert result is False


class TestGetMonthlyStats:
    """Тесты метода get_monthly_stats."""

    @pytest.mark.asyncio
    async def test_get_monthly_stats_success(self, manager):
        """Тест успешного получения месячной статистики."""
        mock_activity1 = MagicMock(game_name="Dota 2", total_seconds_in_month=36000)
        mock_activity2 = MagicMock(game_name="CS:GO", total_seconds_in_month=18000)

        with patch("utils.activity_data_manager.MonthlyActivity.filter") as mock_filter:
            future = asyncio.Future()
            future.set_result([mock_activity1, mock_activity2])
            mock_filter.return_value = future

            result = await manager.get_monthly_stats(123, 2024, 5)

            expected = {"Dota 2": 36000, "CS:GO": 18000}
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_monthly_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных."""
        with patch(
            "utils.activity_data_manager.MonthlyActivity.filter",
            side_effect=Exception("Database error"),
        ):
            result = await manager.get_monthly_stats(123, 2024, 5)
            assert result == {}


class TestGetAggregatedMonthlyStats:
    """Тесты метода get_aggregated_monthly_stats."""

    @pytest.mark.asyncio
    async def test_get_aggregated_monthly_stats_success(self, manager):
        """Тест успешного получения агрегированной месячной статистики."""
        mock_activity1 = MagicMock(
            discord_user_id=123, game_name="Dota 2", total_seconds_in_month=36000
        )
        mock_activity2 = MagicMock(
            discord_user_id=123, game_name="CS:GO", total_seconds_in_month=18000
        )
        mock_activity3 = MagicMock(
            discord_user_id=456, game_name="Dota 2", total_seconds_in_month=72000
        )

        with patch("utils.activity_data_manager.MonthlyActivity.filter") as mock_filter:
            future = asyncio.Future()
            future.set_result([mock_activity1, mock_activity2, mock_activity3])
            mock_filter.return_value = future

            result = await manager.get_aggregated_monthly_stats(2024, 5)

            expected = {123: {"Dota 2": 36000, "CS:GO": 18000}, 456: {"Dota 2": 72000}}
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_aggregated_monthly_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных."""
        with patch(
            "utils.activity_data_manager.MonthlyActivity.filter",
            side_effect=Exception("Database error"),
        ):
            result = await manager.get_aggregated_monthly_stats(2024, 5)
            assert result == {}


class TestGetAllTimeStats:
    """Тесты метода get_all_time_stats."""

    @pytest.mark.asyncio
    async def test_get_all_time_stats_success(self, manager):
        """Тест успешного получения статистики за все время."""
        # Мокаем месячные данные
        mock_monthly_data = [
            {"game_name": "Dota 2", "total_seconds": 360000},
            {"game_name": "CS:GO", "total_seconds": 180000},
        ]

        # Мокаем дневные данные
        mock_daily_activity1 = MagicMock(game_name="Dota 2", seconds_played_today=3600)
        mock_daily_activity2 = MagicMock(game_name="Valorant", seconds_played_today=1800)

        with patch("utils.activity_data_manager.MonthlyActivity.filter") as mock_monthly_filter:
            # Настройка цепочки вызовов для MonthlyActivity
            mock_group_by = MagicMock()
            mock_annotate = MagicMock()
            # В Tortoise: await Model.filter()...values() возвращает список
            # Но здесь мы мокаем результат await

            # Сложная цепочка моков для Tortoise ORM query builder
            # await MonthlyActivity.filter(...).group_by(...).annotate(...).values(...)

            # Проще замокать весь chain
            mock_values_future = asyncio.Future()
            mock_values_future.set_result(mock_monthly_data)

            mock_annotate.values.return_value = mock_values_future
            mock_group_by.annotate.return_value = mock_annotate
            mock_monthly_filter.return_value.group_by.return_value = mock_group_by

            with patch("utils.activity_data_manager.DailyActivity.filter") as mock_daily_filter:
                daily_future = asyncio.Future()
                daily_future.set_result([mock_daily_activity1, mock_daily_activity2])
                mock_daily_filter.return_value = daily_future

                result = await manager.get_all_time_stats(123)

                expected = {
                    "Dota 2": 363600,  # 360000 + 3600
                    "CS:GO": 180000,
                    "Valorant": 1800,
                }
                assert result == expected

    @pytest.mark.asyncio
    async def test_get_all_time_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных."""
        with patch(
            "utils.activity_data_manager.MonthlyActivity.filter",
            side_effect=Exception("Database error"),
        ):
            result = await manager.get_all_time_stats(123)
            assert result == {}


class TestProfilePeriodQueries:
    """Тесты агрегатов, используемых интерактивным профилем."""

    @pytest.mark.asyncio
    async def test_get_daily_stats_by_prefix_sums_games(self, manager):
        rows = [
            MagicMock(game_name="Dota 2", seconds_played_today=120),
            MagicMock(game_name="Dota 2", seconds_played_today=180),
            MagicMock(game_name="CS2", seconds_played_today=60),
        ]
        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            future = asyncio.Future()
            future.set_result(rows)
            mock_filter.return_value = future

            result = await manager.get_daily_stats_by_prefix(123, "2026-07")

        assert result == {"Dota 2": 300, "CS2": 60}
        mock_filter.assert_called_once_with(
            discord_user_id=123,
            date__startswith="2026-07",
            seconds_played_today__gt=0,
        )

    @pytest.mark.asyncio
    async def test_get_yearly_stats_aggregates_months(self, manager):
        values = [
            {"game_name": "Dota 2", "total_seconds": 300},
            {"game_name": "CS2", "total_seconds": 60},
        ]
        with patch("utils.activity_data_manager.MonthlyActivity.filter") as mock_filter:
            future = asyncio.Future()
            future.set_result(values)
            mock_filter.return_value.group_by.return_value.annotate.return_value.values.return_value = future

            result = await manager.get_yearly_stats(123, 2026)

        assert result == {"Dota 2": 300, "CS2": 60}
        mock_filter.assert_called_once_with(
            discord_user_id=123,
            year=2026,
            total_seconds_in_month__gt=0,
        )
