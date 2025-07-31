"""Тесты для команды quote в коге FunCog.

Этот модуль содержит тесты для функциональности команды quote,
включая тестирование команды, автокомплита и интеграционные тесты.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from cogs.fun import FunCog


@pytest.fixture
def fun_cog():
    """Фикстура для создания экземпляра FunCog."""
    bot = MagicMock(spec=commands.Bot)
    return FunCog(bot)


class TestQuoteCommand:
    """Тесты для команды quote."""

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quote_command_no_user_no_users_available(self, mock_scan, fun_cog):
        """Тест команды quote без пользователя когда нет доступных пользователей."""
        # Настройка моков
        mock_scan.return_value = []

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        await fun_cog.quote.callback(fun_cog, mock_ctx, None)

        # Проверяем, что отправлено сообщение об ошибке
        mock_ctx.send.assert_called_once_with("❌ Цитаты не найдены!", ephemeral=True)

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    @patch("cogs.fun.send_random_quote_image")
    @patch("cogs.fun.random.choice")
    async def test_quote_command_no_user_with_users_available(
        self, mock_choice, mock_send, mock_scan, fun_cog
    ):
        """Тест команды quote без пользователя когда есть доступные пользователи."""
        # Настройка моков
        mock_scan.return_value = ["user1", "user2"]
        mock_choice.return_value = "user1"
        mock_send.return_value = None

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        await fun_cog.quote.callback(fun_cog, mock_ctx, None)

        # Проверяем, что выбран случайный пользователь и отправлена цитата
        mock_choice.assert_called_once_with(["user1", "user2"])
        mock_send.assert_called_once_with(mock_ctx, "user1", embed=False)

    @pytest.mark.asyncio
    @patch("cogs.fun.validate_folder_exists")
    @patch("cogs.fun.send_random_quote_image")
    async def test_quote_command_with_valid_user(self, mock_send, mock_validate, fun_cog):
        """Тест команды quote с валидным пользователем."""
        # Настройка моков
        mock_validate.return_value = True
        mock_send.return_value = None

        mock_ctx = MagicMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        await fun_cog.quote.callback(fun_cog, mock_ctx, "test_user")

        # Проверяем, что функция отправки была вызвана
        mock_validate.assert_called_once_with("test_user")
        mock_send.assert_called_once_with(mock_ctx, "test_user", embed=False)

    @pytest.mark.asyncio
    @patch("cogs.fun.validate_folder_exists")
    async def test_quote_command_with_invalid_user(self, mock_validate, fun_cog):
        """Тест команды quote с невалидным пользователем."""
        # Настройка моков
        mock_validate.return_value = False

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        await fun_cog.quote.callback(fun_cog, mock_ctx, "invalid_user")

        # Проверяем, что отправлено сообщение об ошибке
        mock_ctx.send.assert_called_once_with(
            "❌ Цитаты пользователя `invalid_user` не найдены!", ephemeral=True
        )

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quote_autocomplete_no_input(self, mock_scan, fun_cog):
        """Тест автокомплита без ввода пользователя."""
        mock_scan.return_value = ["user1", "user2", "user3"]

        mock_interaction = MagicMock()

        result = await fun_cog.quote_autocomplete(mock_interaction, "")

        assert len(result) == 3
        assert all(choice.name in ["user1", "user2", "user3"] for choice in result)
        assert all(choice.value in ["user1", "user2", "user3"] for choice in result)

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quote_autocomplete_with_filter(self, mock_scan, fun_cog):
        """Тест автокомплита с фильтрацией по вводу."""
        mock_scan.return_value = ["user1", "test_user", "another"]

        mock_interaction = MagicMock()

        result = await fun_cog.quote_autocomplete(mock_interaction, "user")

        # Должны вернуться только пользователи, содержащие "user"
        assert len(result) == 2
        user_names = [choice.name for choice in result]
        assert "user1" in user_names
        assert "test_user" in user_names
        assert "another" not in user_names

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quote_autocomplete_limit_25(self, mock_scan, fun_cog):
        """Тест ограничения автокомплита до 25 вариантов."""
        # Создаем 30 пользователей
        users = [f"user{i}" for i in range(30)]
        mock_scan.return_value = users

        mock_interaction = MagicMock()

        result = await fun_cog.quote_autocomplete(mock_interaction, "")

        # Должно вернуться максимум 25 вариантов
        assert len(result) <= 25

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quote_autocomplete_error_handling(self, mock_scan, fun_cog):
        """Тест обработки ошибок в автокомплите."""
        mock_scan.side_effect = Exception("Test error")

        mock_interaction = MagicMock()

        result = await fun_cog.quote_autocomplete(mock_interaction, "test")

        # При ошибке должен вернуться пустой список
        assert result == []

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quote_autocomplete_case_insensitive(self, mock_scan, fun_cog):
        """Тест регистронезависимой фильтрации в автокомплите."""
        mock_scan.return_value = ["TestUser", "UPPERCASE", "lowercase"]

        mock_interaction = MagicMock()

        # Тестируем поиск в нижнем регистре
        result = await fun_cog.quote_autocomplete(mock_interaction, "test")

        assert len(result) == 1
        assert result[0].name == "TestUser"

        # Тестируем поиск в верхнем регистре
        result = await fun_cog.quote_autocomplete(mock_interaction, "UPPER")

        assert len(result) == 1
        assert result[0].name == "UPPERCASE"


class TestQuoteCommandIntegration:
    """Интеграционные тесты для команды quote."""

    @pytest.mark.asyncio
    @patch("cogs.fun.validate_folder_exists")
    @patch("cogs.fun.send_random_quote_image")
    async def test_quote_command_full_flow_with_user(
        self, mock_send, mock_validate, fun_cog
    ):
        """Тест полного потока команды quote с указанием пользователя."""
        # Настройка моков для успешного выполнения
        mock_validate.return_value = True
        mock_send.return_value = None

        mock_ctx = MagicMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        await fun_cog.quote.callback(fun_cog, mock_ctx, "test_user")

        # Проверяем последовательность вызовов
        mock_validate.assert_called_once_with("test_user")
        mock_send.assert_called_once_with(mock_ctx, "test_user", embed=False)

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    @patch("cogs.fun.send_random_quote_image")
    @patch("cogs.fun.random.choice")
    async def test_quote_command_full_flow_without_user(
        self, mock_choice, mock_send, mock_scan, fun_cog
    ):
        """Тест полного потока команды quote без указания пользователя."""
        # Настройка моков
        mock_scan.return_value = ["user1", "user2"]
        mock_choice.return_value = "user1"
        mock_send.return_value = None

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        await fun_cog.quote.callback(fun_cog, mock_ctx, None)

        # Проверяем последовательность вызовов
        mock_scan.assert_called_once()
        mock_choice.assert_called_once_with(["user1", "user2"])
        mock_send.assert_called_once_with(mock_ctx, "user1", embed=False)
