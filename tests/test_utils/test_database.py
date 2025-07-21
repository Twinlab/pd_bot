"""Тесты для модуля database."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.database import (
    DB_PATH,
    clear_anime_cache,
    execute_query,
    execute_update,
    initialize_database,
    load_anime_cache,
    save_anime_cache_item,
)


class TestInitializeDatabase:
    """Тесты для функции initialize_database."""

    @pytest.mark.asyncio
    async def test_initialize_database(self):
        """Тест инициализации базы данных."""
        # Патчим aiosqlite.connect и Path.mkdir
        with patch("aiosqlite.connect") as mock_connect, patch("pathlib.Path.mkdir"):
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            await initialize_database()

            # Проверяем результат
            mock_connect.assert_called_once_with(DB_PATH)
            assert mock_connection.execute.call_count > 0  # Проверяем, что выполнялись SQL-запросы
            mock_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_database_error(self):
        """Тест обработки ошибок."""
        # Патчим aiosqlite.connect, чтобы он вызывал исключение
        with patch("aiosqlite.connect", side_effect=Exception("Test error")), patch(
            "utils.database.logger"
        ) as mock_logger:
            # Вызываем функцию и проверяем, что исключение проброшено
            with pytest.raises(Exception, match="Test error"):
                await initialize_database()

            # Проверяем, что ошибка залогирована
            mock_logger.critical.assert_called_once()
            assert "Test error" in mock_logger.critical.call_args[0][0]


class TestExecuteQuery:
    """Тесты для функции execute_query."""

    @pytest.mark.asyncio
    async def test_execute_query_no_params(self):
        """Тест выполнения запроса без параметров."""
        # Патчим aiosqlite.connect
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_cursor = AsyncMock()
            mock_connection.execute.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                {"id": 1, "name": "Test1"},
                {"id": 2, "name": "Test2"},
            ]
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            result = await execute_query("SELECT * FROM test")

            # Проверяем результат
            mock_connect.assert_called_once_with(DB_PATH)
            mock_connection.execute.assert_called_once_with("SELECT * FROM test", ())
            mock_cursor.fetchall.assert_called_once()
            assert len(result) == 2
            assert result[0]["id"] == 1
            assert result[0]["name"] == "Test1"
            assert result[1]["id"] == 2
            assert result[1]["name"] == "Test2"

    @pytest.mark.asyncio
    async def test_execute_query_with_params(self):
        """Тест выполнения запроса с параметрами."""
        # Патчим aiosqlite.connect
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_cursor = AsyncMock()
            mock_connection.execute.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [{"id": 1, "name": "Test"}]
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            result = await execute_query("SELECT * FROM test WHERE id = ?", (1,))

            # Проверяем результат
            mock_connect.assert_called_once_with(DB_PATH)
            mock_connection.execute.assert_called_once_with("SELECT * FROM test WHERE id = ?", (1,))
            mock_cursor.fetchall.assert_called_once()
            assert len(result) == 1
            assert result[0]["id"] == 1
            assert result[0]["name"] == "Test"

    @pytest.mark.asyncio
    async def test_execute_query_error(self):
        """Тест обработки ошибок."""
        # Патчим aiosqlite.connect
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок, чтобы он вызывал исключение
            mock_connection = AsyncMock()
            mock_connection.execute.side_effect = Exception("Test error")
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Патчим логгер
            with patch("utils.database.logger") as mock_logger:
                # Вызываем функцию и проверяем, что исключение проброшено
                with pytest.raises(Exception, match="Test error"):
                    await execute_query("SELECT * FROM test")

                # Проверяем, что ошибка залогирована
                mock_logger.error.assert_called_once()
                assert "Test error" in mock_logger.error.call_args[0][0]


class TestExecuteUpdate:
    """Тесты для функции execute_update."""

    @pytest.mark.asyncio
    async def test_execute_update_no_params(self):
        """Тест выполнения обновления без параметров."""
        # Патчим aiosqlite.connect
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_cursor = AsyncMock()
            mock_cursor.rowcount = 1
            mock_connection.execute.return_value = mock_cursor
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            result = await execute_update("UPDATE test SET name = 'New Name'")

            # Проверяем результат
            mock_connect.assert_called_once_with(DB_PATH)
            mock_connection.execute.assert_called_once_with("UPDATE test SET name = 'New Name'", ())
            mock_connection.commit.assert_called_once()
            assert result == 1

    @pytest.mark.asyncio
    async def test_execute_update_with_params(self):
        """Тест выполнения обновления с параметрами."""
        # Патчим aiosqlite.connect
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_cursor = AsyncMock()
            mock_cursor.rowcount = 1
            mock_connection.execute.return_value = mock_cursor
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            result = await execute_update("UPDATE test SET name = ? WHERE id = ?", ("New Name", 1))

            # Проверяем результат
            mock_connect.assert_called_once_with(DB_PATH)
            mock_connection.execute.assert_called_once_with(
                "UPDATE test SET name = ? WHERE id = ?", ("New Name", 1)
            )
            mock_connection.commit.assert_called_once()
            assert result == 1

    @pytest.mark.asyncio
    async def test_execute_update_error(self):
        """Тест обработки ошибок."""
        # Патчим aiosqlite.connect
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок, чтобы он вызывал исключение
            mock_connection = AsyncMock()
            mock_connection.execute.side_effect = Exception("Test error")
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Патчим логгер
            with patch("utils.database.logger") as mock_logger:
                # Вызываем функцию и проверяем, что исключение проброшено
                with pytest.raises(Exception, match="Test error"):
                    await execute_update("UPDATE test SET name = 'New Name'")

                # Проверяем, что ошибка залогирована
                mock_logger.error.assert_called_once()
                assert "Test error" in mock_logger.error.call_args[0][0]


class TestAnimeCacheFunctions:
    """Тесты для функций кеша аниме."""

    @pytest.mark.asyncio
    async def test_load_anime_cache_success(self):
        """Тест успешной загрузки кеша аниме."""
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_cursor = AsyncMock()
            mock_connection.execute.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [(123,), (456,), (789,)]
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            result = await load_anime_cache()

            # Проверяем результат
            mock_connect.assert_called_once_with(DB_PATH)
            mock_connection.execute.assert_called_once()
            assert result == [123, 456, 789]

    @pytest.mark.asyncio
    async def test_load_anime_cache_empty(self):
        """Тест загрузки пустого кеша аниме."""
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_cursor = AsyncMock()
            mock_connection.execute.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            result = await load_anime_cache()

            # Проверяем результат
            assert result == []

    @pytest.mark.asyncio
    async def test_load_anime_cache_error(self):
        """Тест обработки ошибки при загрузке кеша."""
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок, чтобы он вызывал исключение
            mock_connection = AsyncMock()
            mock_connection.execute.side_effect = Exception("Test error")
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Патчим логгер
            with patch("utils.database.logger") as mock_logger:
                # Вызываем функцию
                result = await load_anime_cache()

                # Проверяем, что вернулся пустой список
                assert result == []
                
                # Проверяем, что ошибка залогирована
                mock_logger.error.assert_called_once()
                assert "Test error" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_save_anime_cache_item_success(self):
        """Тест успешного сохранения элемента кеша."""
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            await save_anime_cache_item(12345)

            # Проверяем результат
            mock_connect.assert_called_once_with(DB_PATH)
            mock_connection.execute.assert_called_once()
            mock_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_anime_cache_item_error(self):
        """Тест обработки ошибки при сохранении элемента кеша."""
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок, чтобы он вызывал исключение
            mock_connection = AsyncMock()
            mock_connection.execute.side_effect = Exception("Test error")
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Патчим логгер
            with patch("utils.database.logger") as mock_logger:
                # Вызываем функцию (не должна вызывать исключение)
                await save_anime_cache_item(12345)

                # Проверяем, что ошибка залогирована
                mock_logger.error.assert_called_once()
                assert "Test error" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_clear_anime_cache_success(self):
        """Тест успешной очистки кеша аниме."""
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок для контекстного менеджера
            mock_connection = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Вызываем функцию
            await clear_anime_cache()

            # Проверяем результат
            mock_connect.assert_called_once_with(DB_PATH)
            mock_connection.execute.assert_called_once_with("DELETE FROM anime_cache")
            mock_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_anime_cache_error(self):
        """Тест обработки ошибки при очистке кеша."""
        with patch("aiosqlite.connect") as mock_connect:
            # Настраиваем мок, чтобы он вызывал исключение
            mock_connection = AsyncMock()
            mock_connection.execute.side_effect = Exception("Test error")
            mock_connect.return_value.__aenter__.return_value = mock_connection

            # Патчим логгер
            with patch("utils.database.logger") as mock_logger:
                # Вызываем функцию (не должна вызывать исключение)
                await clear_anime_cache()

                # Проверяем, что ошибка залогирована
                mock_logger.error.assert_called_once()
                assert "Test error" in mock_logger.error.call_args[0][0]
