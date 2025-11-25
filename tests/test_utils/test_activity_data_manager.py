"""Тесты для модуля управления данными активности пользователей."""

import asyncio
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from collections import defaultdict

from utils.activity_data_manager import ActivityDataManager
from utils.models import DailyActivity, MonthlyActivity


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
            
            with patch("utils.activity_data_manager.DailyActivity.create", new_callable=AsyncMock) as mock_create:
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
            
            with patch("utils.activity_data_manager.DailyActivity.create", new_callable=AsyncMock) as mock_create:
                await manager.update_activity(123, "Dota 2", 3600)
                
                mock_filter.assert_called_once()
                mock_create.assert_not_called()

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
        with patch("utils.activity_data_manager.DailyActivity.filter", side_effect=Exception("Database error")):
            # Не должно выбрасывать исключение, а логировать ошибку
            await manager.update_activity(123, "Dota 2", 3600)


class TestGetDailyStats:
    """Тесты метода get_daily_stats."""

    @pytest.mark.asyncio
    async def test_get_daily_stats_success(self, manager):
        """Тест успешного получения дневной статистики."""
        mock_activity1 = MagicMock(discord_user_id=123, game_name="Dota 2", seconds_played_today=3600)
        mock_activity2 = MagicMock(discord_user_id=123, game_name="CS:GO", seconds_played_today=1800)
        mock_activity3 = MagicMock(discord_user_id=456, game_name="Dota 2", seconds_played_today=7200)
        
        with patch("utils.activity_data_manager.DailyActivity.filter") as mock_filter:
            # Имитируем awaitable результат filter()
            future = asyncio.Future()
            future.set_result([mock_activity1, mock_activity2, mock_activity3])
            mock_filter.return_value = future
            
            target_date = date(2024, 5, 26)
            result = await manager.get_daily_stats(target_date)
            
            expected = {
                123: {"Dota 2": 3600, "CS:GO": 1800},
                456: {"Dota 2": 7200}
            }
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
        with patch("utils.activity_data_manager.DailyActivity.filter", side_effect=Exception("Database error")):
            target_date = date(2024, 5, 26)
            result = await manager.get_daily_stats(target_date)
            assert result == {}


class TestTransferDailyToMonthly:
    """Тесты метода transfer_daily_to_monthly."""

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_success(self, manager):
        """Тест успешного переноса дневных данных в месячные (создание новой записи)."""
        mock_daily_record = MagicMock(
            discord_user_id=123,
            game_name="Dota 2",
            seconds_played_today=3600
        )
        
        # Мокаем транзакцию
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()
        
        with patch("tortoise.transactions.in_transaction", return_value=mock_transaction):
            with patch("utils.activity_data_manager.DailyActivity.filter") as mock_daily_filter:
                # Мокаем получение записей (первый вызов filter)
                # И удаление (второй вызов filter)
                # Используем side_effect для разных возвращаемых значений
                
                # Нам нужно замокать filter().all() и filter().delete()
                # И filter().update() для MonthlyActivity
                
                mock_daily_queryset = MagicMock()
                mock_daily_queryset.all = AsyncMock(return_value=[mock_daily_record])
                mock_daily_queryset.delete = AsyncMock()
                
                mock_daily_filter.return_value = mock_daily_queryset

                with patch("utils.activity_data_manager.MonthlyActivity.filter") as mock_monthly_filter:
                    # Мокаем update, возвращаем 0 (запись не найдена)
                    mock_monthly_filter.return_value.update = AsyncMock(return_value=0)
                    
                    with patch("utils.activity_data_manager.MonthlyActivity.create", new_callable=AsyncMock) as mock_monthly_create:
                        target_date = date(2024, 5, 26)
                        result = await manager.transfer_daily_to_monthly(target_date)
                        
                        assert result is True
                        mock_monthly_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_update_existing(self, manager):
        """Тест обновления существующей месячной записи."""
        mock_daily_record = MagicMock(
            discord_user_id=123,
            game_name="Dota 2",
            seconds_played_today=3600
        )
        
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()
        
        with patch("tortoise.transactions.in_transaction", return_value=mock_transaction):
            with patch("utils.activity_data_manager.DailyActivity.filter") as mock_daily_filter:
                mock_daily_queryset = MagicMock()
                mock_daily_queryset.all = AsyncMock(return_value=[mock_daily_record])
                mock_daily_queryset.delete = AsyncMock()
                mock_daily_filter.return_value = mock_daily_queryset
                
                with patch("utils.activity_data_manager.MonthlyActivity.filter") as mock_monthly_filter:
                    # Мокаем update, возвращаем 1 (запись обновлена)
                    mock_monthly_filter.return_value.update = AsyncMock(return_value=1)
                    
                    with patch("utils.activity_data_manager.MonthlyActivity.create", new_callable=AsyncMock) as mock_monthly_create:
                        target_date = date(2024, 5, 26)
                        result = await manager.transfer_daily_to_monthly(target_date)
                        
                        assert result is True
                        mock_monthly_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_error(self, manager):
        """Тест обработки ошибки при переносе."""
        with patch("tortoise.transactions.in_transaction", side_effect=Exception("Transaction error")):
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
        with patch("utils.activity_data_manager.MonthlyActivity.filter", side_effect=Exception("Database error")):
            result = await manager.get_monthly_stats(123, 2024, 5)
            assert result == {}


class TestGetAggregatedMonthlyStats:
    """Тесты метода get_aggregated_monthly_stats."""

    @pytest.mark.asyncio
    async def test_get_aggregated_monthly_stats_success(self, manager):
        """Тест успешного получения агрегированной месячной статистики."""
        mock_activity1 = MagicMock(discord_user_id=123, game_name="Dota 2", total_seconds_in_month=36000)
        mock_activity2 = MagicMock(discord_user_id=123, game_name="CS:GO", total_seconds_in_month=18000)
        mock_activity3 = MagicMock(discord_user_id=456, game_name="Dota 2", total_seconds_in_month=72000)
        
        with patch("utils.activity_data_manager.MonthlyActivity.filter") as mock_filter:
            future = asyncio.Future()
            future.set_result([mock_activity1, mock_activity2, mock_activity3])
            mock_filter.return_value = future
            
            result = await manager.get_aggregated_monthly_stats(2024, 5)
            
            expected = {
                123: {"Dota 2": 36000, "CS:GO": 18000},
                456: {"Dota 2": 72000}
            }
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_aggregated_monthly_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных."""
        with patch("utils.activity_data_manager.MonthlyActivity.filter", side_effect=Exception("Database error")):
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
            {"game_name": "CS:GO", "total_seconds": 180000}
        ]
        
        # Мокаем дневные данные
        mock_daily_activity1 = MagicMock(game_name="Dota 2", seconds_played_today=3600)
        mock_daily_activity2 = MagicMock(game_name="Valorant", seconds_played_today=1800)
        
        with patch("utils.activity_data_manager.MonthlyActivity.filter") as mock_monthly_filter:
            # Настройка цепочки вызовов для MonthlyActivity
            mock_group_by = MagicMock()
            mock_annotate = MagicMock()
            mock_values = MagicMock(return_value=mock_monthly_data) # values не асинхронный в цепочке построения запроса, но результат awaitable?
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
                    "Valorant": 1800
                }
                assert result == expected

    @pytest.mark.asyncio
    async def test_get_all_time_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных."""
        with patch("utils.activity_data_manager.MonthlyActivity.filter", side_effect=Exception("Database error")):
            result = await manager.get_all_time_stats(123)
            assert result == {}