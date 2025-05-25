"""Тесты для модуля управления данными активности пользователей."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from collections import defaultdict

from utils.activity_data_manager import ActivityDataManager


class TestActivityDataManagerInit:
    """Тесты инициализации ActivityDataManager."""

    def test_init_default_path(self):
        """Тест инициализации с путем по умолчанию."""
        manager = ActivityDataManager()
        # Проверяем, что путь содержит ожидаемые части
        assert 'bot_data.db' in manager.db_path or 'data' in manager.db_path

    def test_init_custom_path(self):
        """Тест инициализации с пользовательским путем."""
        custom_path = '/custom/path/test.db'
        manager = ActivityDataManager(db_path=custom_path)
        assert manager.db_path == custom_path


class TestUpdateActivity:
    """Тесты метода update_activity."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр ActivityDataManager."""
        return ActivityDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_update_activity_success(self, manager):
        """Тест успешного обновления активности."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            await manager.update_activity(123, "Dota 2", 3600)
            
            # Проверяем, что execute был вызван с правильными параметрами
            mock_conn.execute.assert_called_once()
            call_args = mock_conn.execute.call_args
            assert "INSERT INTO daily_activity" in call_args[0][0]
            assert call_args[0][1] == (123, "Dota 2", date.today().isoformat(), 3600)
            mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_activity_zero_seconds(self, manager):
        """Тест обновления активности с нулевым временем."""
        mock_conn = AsyncMock()
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            await manager.update_activity(123, "Dota 2", 0)
            
            # Не должно быть вызовов к базе данных
            mock_conn.execute.assert_not_called()
            mock_conn.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_activity_negative_seconds(self, manager):
        """Тест обновления активности с отрицательным временем."""
        mock_conn = AsyncMock()
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            await manager.update_activity(123, "Dota 2", -100)
            
            # Не должно быть вызовов к базе данных
            mock_conn.execute.assert_not_called()
            mock_conn.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_activity_database_error(self, manager):
        """Тест обработки ошибки базы данных при обновлении активности."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.activity_data_manager.logger') as mock_logger:
                await manager.update_activity(123, "Dota 2", 3600)
                
                # Проверяем, что ошибка была залогирована
                mock_logger.error.assert_called_once()
                assert "Ошибка при обновлении daily_activity в БД" in mock_logger.error.call_args[0][0]


class TestGetDailyStats:
    """Тесты метода get_daily_stats."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр ActivityDataManager."""
        return ActivityDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_get_daily_stats_success(self, manager):
        """Тест успешного получения дневной статистики."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        
        # Настраиваем возвращаемые данные
        mock_row1 = (123, "Dota 2", 3600)
        mock_row2 = (123, "CS:GO", 1800)
        mock_row3 = (456, "Dota 2", 7200)
        mock_cursor.__aiter__.return_value = [mock_row1, mock_row2, mock_row3]
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
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
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = []
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            target_date = date(2024, 5, 26)
            result = await manager.get_daily_stats(target_date)
            
            assert result == {}

    @pytest.mark.asyncio
    async def test_get_daily_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении дневной статистики."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.activity_data_manager.logger') as mock_logger:
                target_date = date(2024, 5, 26)
                result = await manager.get_daily_stats(target_date)
                
                assert result == {}
                mock_logger.error.assert_called_once()
                assert "Ошибка при получении daily_stats из БД" in mock_logger.error.call_args[0][0]


class TestTransferDailyToMonthly:
    """Тесты метода transfer_daily_to_monthly."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр ActivityDataManager."""
        return ActivityDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_success(self, manager):
        """Тест успешного переноса дневных данных в месячные."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        mock_conn.rollback = AsyncMock()
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            target_date = date(2024, 5, 26)
            result = await manager.transfer_daily_to_monthly(target_date)
            
            assert result is True
            
            # Проверяем последовательность вызовов
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3  # BEGIN, INSERT, DELETE
            assert calls[0][0][0] == "BEGIN"
            assert "INSERT INTO monthly_activity" in calls[1][0][0]
            assert "DELETE FROM daily_activity" in calls[2][0][0]
            
            mock_conn.commit.assert_called_once()
            mock_conn.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_inner_exception(self, manager):
        """Тест обработки ошибки внутри транзакции."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        mock_conn.rollback = AsyncMock()
        
        # Настраиваем ошибку на втором вызове execute (INSERT)
        mock_conn.execute.side_effect = [None, Exception("Insert error"), None]
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            with patch('utils.activity_data_manager.logger') as mock_logger:
                target_date = date(2024, 5, 26)
                result = await manager.transfer_daily_to_monthly(target_date)
                
                assert result is False
                mock_conn.rollback.assert_called_once()
                mock_conn.commit.assert_not_called()
                mock_logger.error.assert_called()
                assert "Ошибка внутри транзакции переноса данных" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_transfer_daily_to_monthly_connection_error(self, manager):
        """Тест обработки ошибки подключения к базе данных."""
        with patch('aiosqlite.connect', side_effect=Exception("Connection error")):
            with patch('utils.activity_data_manager.logger') as mock_logger:
                target_date = date(2024, 5, 26)
                result = await manager.transfer_daily_to_monthly(target_date)
                
                assert result is False
                mock_logger.error.assert_called_once()
                assert "Ошибка подключения к БД при переносе данных" in mock_logger.error.call_args[0][0]


class TestGetMonthlyStats:
    """Тесты метода get_monthly_stats."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр ActivityDataManager."""
        return ActivityDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_get_monthly_stats_success(self, manager):
        """Тест успешного получения месячной статистики."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        
        # Настраиваем возвращаемые данные
        mock_row1 = ("Dota 2", 36000)
        mock_row2 = ("CS:GO", 18000)
        mock_cursor.__aiter__.return_value = [mock_row1, mock_row2]
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_monthly_stats(123, 2024, 5)
            
            expected = {"Dota 2": 36000, "CS:GO": 18000}
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_monthly_stats_empty_result(self, manager):
        """Тест получения месячной статистики без данных."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = []
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_monthly_stats(123, 2024, 5)
            
            assert result == {}

    @pytest.mark.asyncio
    async def test_get_monthly_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении месячной статистики."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.activity_data_manager.logger') as mock_logger:
                result = await manager.get_monthly_stats(123, 2024, 5)
                
                assert result == {}
                mock_logger.error.assert_called_once()
                assert "Ошибка при получении monthly_stats из БД" in mock_logger.error.call_args[0][0]


class TestGetAggregatedMonthlyStats:
    """Тесты метода get_aggregated_monthly_stats."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр ActivityDataManager."""
        return ActivityDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_get_aggregated_monthly_stats_success(self, manager):
        """Тест успешного получения агрегированной месячной статистики."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        
        # Настраиваем возвращаемые данные
        mock_row1 = (123, "Dota 2", 36000)
        mock_row2 = (123, "CS:GO", 18000)
        mock_row3 = (456, "Dota 2", 72000)
        mock_cursor.__aiter__.return_value = [mock_row1, mock_row2, mock_row3]
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_aggregated_monthly_stats(2024, 5)
            
            expected = {
                123: {"Dota 2": 36000, "CS:GO": 18000},
                456: {"Dota 2": 72000}
            }
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_aggregated_monthly_stats_empty_result(self, manager):
        """Тест получения агрегированной месячной статистики без данных."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = []
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_aggregated_monthly_stats(2024, 5)
            
            assert result == {}

    @pytest.mark.asyncio
    async def test_get_aggregated_monthly_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении агрегированной месячной статистики."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.activity_data_manager.logger') as mock_logger:
                result = await manager.get_aggregated_monthly_stats(2024, 5)
                
                assert result == {}
                mock_logger.error.assert_called_once()
                assert "Ошибка при получении агрегированной monthly_stats из БД" in mock_logger.error.call_args[0][0]


class TestGetAllTimeStats:
    """Тесты метода get_all_time_stats."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр ActivityDataManager."""
        return ActivityDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_get_all_time_stats_success(self, manager):
        """Тест успешного получения статистики за все время."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        # Мокаем два курсора - для monthly и daily данных
        mock_monthly_cursor = AsyncMock()
        mock_monthly_row1 = ("Dota 2", 360000)
        mock_monthly_row2 = ("CS:GO", 180000)
        mock_monthly_cursor.__aiter__.return_value = [mock_monthly_row1, mock_monthly_row2]
        mock_monthly_cursor.__aenter__.return_value = mock_monthly_cursor
        
        mock_daily_cursor = AsyncMock()
        mock_daily_row1 = ("Dota 2", 3600)
        mock_daily_row2 = ("Valorant", 1800)
        mock_daily_cursor.__aiter__.return_value = [mock_daily_row1, mock_daily_row2]
        mock_daily_cursor.__aenter__.return_value = mock_daily_cursor
        
        mock_conn.execute = MagicMock(side_effect=[mock_monthly_cursor, mock_daily_cursor])
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_all_time_stats(123)
            
            expected = {
                "Dota 2": 363600,  # 360000 + 3600
                "CS:GO": 180000,
                "Valorant": 1800
            }
            assert result == expected
            
            # Проверяем, что было два вызова execute
            assert mock_conn.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_get_all_time_stats_only_monthly_data(self, manager):
        """Тест получения статистики за все время только с месячными данными."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        mock_monthly_cursor = AsyncMock()
        mock_monthly_row1 = ("Dota 2", 360000)
        mock_monthly_row2 = ("CS:GO", 180000)
        mock_monthly_cursor.__aiter__.return_value = [mock_monthly_row1, mock_monthly_row2]
        mock_monthly_cursor.__aenter__.return_value = mock_monthly_cursor
        
        mock_daily_cursor = AsyncMock()
        mock_daily_cursor.__aiter__.return_value = []
        mock_daily_cursor.__aenter__.return_value = mock_daily_cursor
        
        mock_conn.execute = MagicMock(side_effect=[mock_monthly_cursor, mock_daily_cursor])
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_all_time_stats(123)
            
            expected = {"Dota 2": 360000, "CS:GO": 180000}
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_all_time_stats_only_daily_data(self, manager):
        """Тест получения статистики за все время только с дневными данными."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        mock_monthly_cursor = AsyncMock()
        mock_monthly_cursor.__aiter__.return_value = []
        mock_monthly_cursor.__aenter__.return_value = mock_monthly_cursor
        
        mock_daily_cursor = AsyncMock()
        mock_daily_row1 = ("Dota 2", 3600)
        mock_daily_row2 = ("Valorant", 1800)
        mock_daily_cursor.__aiter__.return_value = [mock_daily_row1, mock_daily_row2]
        mock_daily_cursor.__aenter__.return_value = mock_daily_cursor
        
        mock_conn.execute = MagicMock(side_effect=[mock_monthly_cursor, mock_daily_cursor])
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_all_time_stats(123)
            
            expected = {"Dota 2": 3600, "Valorant": 1800}
            assert result == expected

    @pytest.mark.asyncio
    async def test_get_all_time_stats_no_data(self, manager):
        """Тест получения статистики за все время без данных."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = []
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_all_time_stats(123)
            
            assert result == {}

    @pytest.mark.asyncio
    async def test_get_all_time_stats_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении статистики за все время."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.activity_data_manager.logger') as mock_logger:
                result = await manager.get_all_time_stats(123)
                
                assert result == {}
                mock_logger.error.assert_called_once()
                assert "Ошибка при получении all_time_stats из БД" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_all_time_stats_with_today_date_mock(self, manager):
        """Тест получения статистики за все время с мокированием сегодняшней даты."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        mock_monthly_cursor = AsyncMock()
        mock_monthly_row1 = ("Dota 2", 360000)
        mock_monthly_cursor.__aiter__.return_value = [mock_monthly_row1]
        mock_monthly_cursor.__aenter__.return_value = mock_monthly_cursor
        
        mock_daily_cursor = AsyncMock()
        mock_daily_row1 = ("Dota 2", 3600)
        mock_daily_cursor.__aiter__.return_value = [mock_daily_row1]
        mock_daily_cursor.__aenter__.return_value = mock_daily_cursor
        
        mock_conn.execute = MagicMock(side_effect=[mock_monthly_cursor, mock_daily_cursor])
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            with patch('utils.activity_data_manager.date') as mock_date:
                mock_today = MagicMock()
                mock_today.isoformat.return_value = "2024-05-26"
                mock_date.today.return_value = mock_today
                
                result = await manager.get_all_time_stats(123)
                
                expected = {"Dota 2": 363600}  # 360000 + 3600
                assert result == expected
                
                # Проверяем, что второй запрос использует правильную дату
                daily_call_args = mock_conn.execute.call_args_list[1]
                assert daily_call_args[0][1] == (123, "2024-05-26")
