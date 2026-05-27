"""Тесты для модуля database."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tortoise import Tortoise

from utils.database import DB_PATH, close_database, initialize_database


class TestDatabase:
    """Тесты для функций работы с базой данных."""

    @pytest.mark.asyncio
    async def test_initialize_database(self):
        """Тест инициализации базы данных."""
        mock_conn = MagicMock()
        mock_conn.execute_script = AsyncMock()
        with patch("tortoise.Tortoise.init", new_callable=AsyncMock) as mock_init, patch(
            "tortoise.Tortoise.generate_schemas", new_callable=AsyncMock
        ) as mock_generate, patch("pathlib.Path.mkdir") as mock_mkdir, patch(
            "utils.database.connections.get", return_value=mock_conn
        ):
            await initialize_database()

            mock_mkdir.assert_called_once()
            mock_init.assert_called_once()
            mock_generate.assert_called_once()
            # WAL/sync/busy_timeout PRAGMA должны быть выставлены.
            mock_conn.execute_script.assert_awaited_once()
            script = mock_conn.execute_script.await_args.args[0]
            assert "WAL" in script and "busy_timeout" in script

            # Проверяем аргументы init
            call_args = mock_init.call_args
            assert call_args.kwargs["db_url"] == f"sqlite://{DB_PATH}"
            assert "utils.models" in call_args.kwargs["modules"]["models"]

    @pytest.mark.asyncio
    async def test_initialize_database_error(self):
        """Тест обработки ошибок при инициализации."""
        with patch(
            "tortoise.Tortoise.init", side_effect=Exception("Test error")
        ), patch("utils.database.logger") as mock_logger, patch("pathlib.Path.mkdir"):
            with pytest.raises(Exception, match="Test error"):
                await initialize_database()

            mock_logger.critical.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_database(self):
        """Тест закрытия соединения с базой данных."""
        with patch("tortoise.Tortoise.close_connections", new_callable=AsyncMock) as mock_close:
            await close_database()
            mock_close.assert_called_once()
