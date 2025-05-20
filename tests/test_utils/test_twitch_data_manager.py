import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from utils.twitch_data_manager import TwitchDataManager


@pytest.fixture
def twitch_manager():
    """Фикстура для создания экземпляра TwitchDataManager с тестовой БД."""
    return TwitchDataManager(db_path=":memory:")


@pytest.fixture
def mock_db_connection():
    """Фикстура для создания мока соединения с БД."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    conn.close = AsyncMock()
    return conn


@pytest.fixture
def mock_cursor():
    """Фикстура для создания мока курсора БД."""
    cursor = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=None)
    cursor.fetchall = AsyncMock(return_value=[])
    cursor.__aiter__ = AsyncMock()
    cursor.__anext__ = AsyncMock()
    cursor.rowcount = 1
    return cursor


class TestTwitchDataManager:
    """Тесты для класса TwitchDataManager."""

    @pytest.mark.asyncio
    async def test_initialize_table_success(self, twitch_manager):
        """Тест успешной инициализации таблицы."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        
        with patch("aiosqlite.connect", return_value=mock_conn) as mock_connect:
            result = await twitch_manager.initialize_table()
            
            mock_connect.assert_called_once_with(twitch_manager.db_path)
            assert mock_conn.execute.call_count == 2
            assert "CREATE TABLE IF NOT EXISTS twitch_streamers" in mock_conn.execute.call_args_list[0][0][0]
            assert "CREATE INDEX IF NOT EXISTS idx_twitch_streamers_username" in mock_conn.execute.call_args_list[1][0][0]
            mock_conn.commit.assert_called_once()
            assert result is True

    @pytest.mark.asyncio
    async def test_initialize_table_exception(self, twitch_manager):
        """Тест обработки исключения при инициализации таблицы."""
        with patch("aiosqlite.connect", side_effect=Exception("Test DB Error")), \
             patch("utils.twitch_data_manager.logger.error") as mock_logger_error:
            result = await twitch_manager.initialize_table()
            
            # Проверяем, что ошибка была залогирована
            mock_logger_error.assert_called_once()
            assert "Ошибка при инициализации таблицы twitch_streamers" in mock_logger_error.call_args[0][0]
            
            # Проверяем результат
            assert result is False

    @pytest.mark.asyncio
    async def test_add_streamer_new(self, twitch_manager):
        """Тест добавления нового стримера."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = None

        class CursorMock(AsyncMock):
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return None
            def __await__(self):
                async def dummy(): return None
                return dummy().__await__()

        class CursorMock(AsyncMock):
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return None
            def __await__(self):
                async def dummy(): return None
                return dummy().__await__()
            async def fetchone(self):
                print("DEBUG async fetchone called")
                return None

        mock_cursor = CursorMock()

        # Первый вызов execute (SELECT) — mock_cursor, второй (INSERT) — AsyncMock
        class AwaitableNone:
            def __await__(self):
                async def dummy(): return None
                return dummy().__await__()

        insert_cursor = AwaitableNone()
        # Для async with db.execute(...) as cursor вернуть mock_cursor
        mock_execute = MagicMock()
        mock_execute.__aenter__.return_value = mock_cursor
        mock_execute.__aexit__.return_value = None
        mock_conn.execute = MagicMock(side_effect=[mock_execute, insert_cursor])

        with patch("aiosqlite.connect", return_value=mock_conn):
            result = await twitch_manager.add_streamer(
                guild_id=1, channel_id=2, twitch_username="testuser", twitch_id="123456"
            )

            print("DEBUG execute.call_args_list:", mock_conn.execute.call_args_list)
            assert "SELECT 1 FROM twitch_streamers" in mock_conn.execute.call_args_list[0][0][0]
            assert "INSERT INTO twitch_streamers" in mock_conn.execute.call_args_list[1][0][0]
            mock_conn.commit.assert_called_once()
            assert result is True

    @pytest.mark.asyncio
    async def test_add_streamer_existing(self, twitch_manager):
        """Тест обновления существующего стримера."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = (1,)

        class CursorMock(AsyncMock):
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return None
            def __await__(self):
                async def dummy(): return None
                return dummy().__await__()

        mock_cursor = CursorMock()
        mock_cursor.fetchone.return_value = (1,)

        mock_conn.execute = MagicMock(return_value=mock_cursor)

        with patch("aiosqlite.connect", return_value=mock_conn):
            result = await twitch_manager.add_streamer(
                guild_id=1, channel_id=2, twitch_username="testuser", twitch_id="123456"
            )

            assert "SELECT 1 FROM twitch_streamers" in mock_conn.execute.call_args_list[0][0][0]
            assert "UPDATE twitch_streamers SET channel_id" in mock_conn.execute.call_args_list[1][0][0]
            mock_conn.commit.assert_called_once()
            assert result is True

    @pytest.mark.asyncio
    async def test_add_streamer_lowercase(self, twitch_manager):
        """Тест приведения имени пользователя к нижнему регистру."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = None

        class CursorMock(AsyncMock):
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return None
            def __await__(self):
                async def dummy(): return None
                return dummy().__await__()

        mock_cursor = CursorMock()
        mock_cursor.fetchone.return_value = None

        mock_conn.execute = MagicMock(return_value=mock_cursor)

        with patch("aiosqlite.connect", return_value=mock_conn):
            result = await twitch_manager.add_streamer(
                guild_id=1, channel_id=2, twitch_username="TestUser", twitch_id="123456"
            )

            # Проверяем, что имя пользователя было приведено к нижнему регистру
            assert mock_conn.execute.call_args_list[0][0][1] == (1, "testuser")
            assert result is True

    @pytest.mark.asyncio
    async def test_add_streamer_exception(self, twitch_manager):
        """Тест обработки исключения при добавлении стримера."""
        with patch("aiosqlite.connect", side_effect=Exception("Test DB Error")), \
             patch("utils.twitch_data_manager.logger.error") as mock_logger_error:
            result = await twitch_manager.add_streamer(
                guild_id=1, channel_id=2, twitch_username="testuser", twitch_id="123456"
            )
            
            mock_logger_error.assert_called_once()
            assert "Ошибка при добавлении стримера testuser" in mock_logger_error.call_args[0][0]
            assert result is False

    @pytest.mark.asyncio
    async def test_remove_streamer_success(self, twitch_manager):
        """Тест успешного удаления стримера."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 1
        mock_conn.execute.return_value = mock_cursor
        
        with patch("aiosqlite.connect", return_value=mock_conn):
            result = await twitch_manager.remove_streamer(guild_id=1, twitch_username="testuser")
            
            assert "DELETE FROM twitch_streamers" in mock_conn.execute.call_args[0][0]
            assert mock_conn.execute.call_args[0][1] == (1, "testuser")
            mock_conn.commit.assert_called_once()
            assert result is True

    @pytest.mark.asyncio
    async def test_remove_streamer_not_found(self, twitch_manager):
        """Тест удаления несуществующего стримера."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 0
        mock_conn.execute.return_value = mock_cursor
        
        with patch("aiosqlite.connect", return_value=mock_conn), \
             patch("utils.twitch_data_manager.logger.warning") as mock_logger_warning:
            result = await twitch_manager.remove_streamer(guild_id=1, twitch_username="testuser")
            
            mock_logger_warning.assert_called_once()
            assert "Стример testuser не найден" in mock_logger_warning.call_args[0][0]
            assert result is False

    @pytest.mark.asyncio
    async def test_remove_streamer_lowercase(self, twitch_manager):
        """Тест приведения имени пользователя к нижнему регистру при удалении."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 1
        mock_conn.execute.return_value = mock_cursor
        
        with patch("aiosqlite.connect", return_value=mock_conn):
            result = await twitch_manager.remove_streamer(guild_id=1, twitch_username="TestUser")
            
            assert mock_conn.execute.call_args[0][1] == (1, "testuser")
            assert result is True

    @pytest.mark.asyncio
    async def test_remove_streamer_exception(self, twitch_manager):
        """Тест обработки исключения при удалении стримера."""
        with patch("aiosqlite.connect", side_effect=Exception("Test DB Error")), \
             patch("utils.twitch_data_manager.logger.error") as mock_logger_error:
            result = await twitch_manager.remove_streamer(guild_id=1, twitch_username="testuser")
            
            mock_logger_error.assert_called_once()
            assert "Ошибка при удалении стримера testuser" in mock_logger_error.call_args[0][0]
            assert result is False

    @pytest.mark.asyncio
    async def test_get_streamers_success(self, twitch_manager):
        """Тест успешного получения списка стримеров для сервера."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_cursor = AsyncMock()
        
        # Настраиваем возвращаемые данные
        mock_row1 = {"guild_id": 1, "channel_id": 2, "twitch_username": "user1", "twitch_id": "123"}
        mock_row2 = {"guild_id": 1, "channel_id": 3, "twitch_username": "user2", "twitch_id": "456"}
        mock_cursor.__aiter__.return_value = [mock_row1, mock_row2]
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_conn.execute = MagicMock(return_value=mock_cursor)

        with patch("aiosqlite.connect", return_value=mock_conn):
            result = await twitch_manager.get_streamers(guild_id=1)

            assert "SELECT guild_id, channel_id, twitch_username" in mock_conn.execute.call_args[0][0]
            assert mock_conn.execute.call_args[0][1] == (1,)
            assert len(result) == 2
            assert result[0]["twitch_username"] == "user1"
            assert result[1]["twitch_username"] == "user2"

    @pytest.mark.asyncio
    async def test_get_streamers_empty(self, twitch_manager, mock_db_connection):
        """Тест получения пустого списка стримеров."""
        # Настраиваем мок курсора для возврата пустого результата
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = []
        
        # Настраиваем мок соединения
        mock_db_connection.execute.return_value = mock_cursor
        
        with patch("aiosqlite.connect", return_value=mock_db_connection) as mock_connect:
            result = await twitch_manager.get_streamers(guild_id=1)
            
            # Проверяем результат
            assert result == []

    @pytest.mark.asyncio
    async def test_get_streamers_exception(self, twitch_manager):
        """Тест обработки исключения при получении списка стримеров."""
        with patch("aiosqlite.connect", side_effect=Exception("Test DB Error")), \
             patch("utils.twitch_data_manager.logger.error") as mock_logger_error:
            result = await twitch_manager.get_streamers(guild_id=1)
            
            # Проверяем, что ошибка была залогирована
            mock_logger_error.assert_called_once()
            assert "Ошибка при получении стримеров" in mock_logger_error.call_args[0][0]
            
            # Проверяем результат
            assert result == []
