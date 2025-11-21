"""Тесты для модуля database."""

from unittest.mock import AsyncMock, patch

import pytest
from tortoise import Tortoise

from utils.database import DB_PATH, close_database, initialize_database


class TestDatabase:
    """Тесты для функций работы с базой данных."""

    @pytest.mark.asyncio
    async def test_initialize_database(self):
        """Тест инициализации базы данных."""
        with patch("tortoise.Tortoise.init", new_callable=AsyncMock) as mock_init, patch(
            "tortoise.Tortoise.generate_schemas", new_callable=AsyncMock
        ) as mock_generate, patch("pathlib.Path.mkdir") as mock_mkdir:
            await initialize_database()

            mock_mkdir.assert_called_once()
            mock_init.assert_called_once()
            mock_generate.assert_called_once()

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
