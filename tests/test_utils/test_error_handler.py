"""Тесты для модуля error_handler."""

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from utils.error_handler import (
    command_error_handler,
    get_error_message,
    safe_send,
    safe_send_error,
)


class TestCommandErrorHandler:
    """Тесты для декоратора command_error_handler."""

    @pytest.mark.asyncio
    async def test_command_error_handler_success(self):
        """Тест успешного выполнения команды."""
        # Создаем мок-функцию, которая не вызывает исключений
        async def mock_command(self, ctx, *args, **kwargs):
            return "success"

        # Применяем декоратор
        decorated = command_error_handler(mock_command)

        # Создаем моки для self и ctx
        self_mock = MagicMock()
        self_mock.bot = MagicMock()
        ctx_mock = MagicMock()

        # Вызываем декорированную функцию
        result = await decorated(self_mock, ctx_mock)

        # Проверяем результат
        assert result == "success"
        # Проверяем, что логирование не вызывалось
        assert not ctx_mock.send.called

    @pytest.mark.asyncio
    async def test_command_error_handler_missing_argument(self):
        """Тест обработки исключения commands.MissingRequiredArgument."""
        # Создаем мок-функцию, которая вызывает исключение
        async def mock_command(self, ctx, *args, **kwargs):
            param = MagicMock()
            param.name = "test_param"
            raise commands.MissingRequiredArgument(param)

        # Применяем декоратор
        decorated = command_error_handler(mock_command)

        # Создаем моки для self и ctx
        self_mock = MagicMock()
        self_mock.bot = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.command = MagicMock()
        ctx_mock.command.name = "test_command"
        ctx_mock.author = MagicMock()
        ctx_mock.guild = MagicMock()
        ctx_mock.channel = MagicMock()
        ctx_mock.message = MagicMock()

        # Патчим функцию safe_send_error
        with patch("utils.error_handler.safe_send_error") as mock_safe_send_error, patch(
            "utils.error_handler.logger"
        ):
            # Вызываем декорированную функцию
            await decorated(self_mock, ctx_mock)

            # Проверяем, что safe_send_error вызвана с правильными аргументами
            mock_safe_send_error.assert_called_once()
            assert "test_param" in mock_safe_send_error.call_args[0][1]

    @pytest.mark.asyncio
    async def test_command_error_handler_bad_argument(self):
        """Тест обработки исключения commands.BadArgument."""
        # Создаем мок-функцию, которая вызывает исключение
        async def mock_command(self, ctx, *args, **kwargs):
            raise commands.BadArgument("Неверный аргумент")

        # Применяем декоратор
        decorated = command_error_handler(mock_command)

        # Создаем моки для self и ctx
        self_mock = MagicMock()
        self_mock.bot = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.command = MagicMock()
        ctx_mock.command.name = "test_command"
        ctx_mock.author = MagicMock()
        ctx_mock.guild = MagicMock()
        ctx_mock.channel = MagicMock()
        ctx_mock.message = MagicMock()

        # Патчим функцию safe_send_error
        with patch("utils.error_handler.safe_send_error") as mock_safe_send_error, patch(
            "utils.error_handler.logger"
        ):
            # Вызываем декорированную функцию
            await decorated(self_mock, ctx_mock)

            # Проверяем, что safe_send_error вызвана с правильными аргументами
            mock_safe_send_error.assert_called_once()
            assert "Неверный аргумент" in mock_safe_send_error.call_args[0][1]

    @pytest.mark.asyncio
    async def test_command_error_handler_missing_permissions(self):
        """Тест обработки исключения commands.MissingPermissions."""
        # Создаем мок-функцию, которая вызывает исключение
        async def mock_command(self, ctx, *args, **kwargs):
            raise commands.MissingPermissions(["manage_messages"])

        # Применяем декоратор
        decorated = command_error_handler(mock_command)

        # Создаем моки для self и ctx
        self_mock = MagicMock()
        self_mock.bot = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.command = MagicMock()
        ctx_mock.command.name = "test_command"
        ctx_mock.author = MagicMock()
        ctx_mock.guild = MagicMock()
        ctx_mock.channel = MagicMock()
        ctx_mock.message = MagicMock()

        # Патчим функцию safe_send_error
        with patch("utils.error_handler.safe_send_error") as mock_safe_send_error, patch(
            "utils.error_handler.logger"
        ):
            # Вызываем декорированную функцию
            await decorated(self_mock, ctx_mock)

            # Проверяем, что safe_send_error вызвана с правильными аргументами
            mock_safe_send_error.assert_called_once()
            assert "недостаточно прав" in mock_safe_send_error.call_args[0][1]

    @pytest.mark.asyncio
    async def test_command_error_handler_command_invoke_error(self):
        """Тест обработки исключения commands.CommandInvokeError."""
        # Создаем мок-функцию, которая вызывает исключение
        async def mock_command(self, ctx, *args, **kwargs):
            original_error = ValueError("Original Error")
            raise commands.CommandInvokeError(original_error)

        # Применяем декоратор
        decorated = command_error_handler(mock_command)

        # Создаем моки для self и ctx
        self_mock = MagicMock()
        self_mock.bot = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.command = MagicMock()
        ctx_mock.command.name = "test_command"
        ctx_mock.author = MagicMock()
        ctx_mock.guild = MagicMock()
        ctx_mock.channel = MagicMock()
        ctx_mock.message = MagicMock()

        # Патчим функцию safe_send_error
        with patch("utils.error_handler.safe_send_error") as mock_safe_send_error, patch(
            "utils.error_handler.logger"
        ):
            # Вызываем декорированную функцию
            await decorated(self_mock, ctx_mock)

            # Проверяем, что safe_send_error вызвана с правильными аргументами
            mock_safe_send_error.assert_called_once()
            assert "Original Error" in mock_safe_send_error.call_args[0][1]


class TestGetErrorMessage:
    """Тесты для функции get_error_message."""

    @pytest.mark.parametrize(
        "error,expected_substring",
        [
            (commands.MissingRequiredArgument(MagicMock(name="test_param")), "test_param"),
            (commands.BadArgument(), "Неверный аргумент"),
            (commands.MissingPermissions(["manage_messages"]), "недостаточно прав"),
            (commands.BotMissingPermissions(["manage_messages"]), "недостаточно прав"),
            (commands.CommandOnCooldown(5, 10, commands.BucketType.default), "перезарядке"),
            (commands.NotOwner(), "владельцу"),
            (discord.HTTPException(MagicMock(), "HTTP Error"), "Discord API"),
            (discord.Forbidden(MagicMock(), "Forbidden"), "Discord API"),
            (discord.NotFound(MagicMock(), "Not Found"), "Discord API"),
            (ValueError("Value Error"), "значения"),
            (TypeError("Type Error"), "типа"),
            (KeyError("Key Error"), "Ключ не найден"),
            (IndexError("Index Error"), "Индекс вне диапазона"),
            (FileNotFoundError("File Not Found"), "Файл не найден"),
            (PermissionError("Permission Error"), "прав доступа"),
            (TimeoutError("Timeout Error"), "время ожидания"),
            (ConnectionError("Connection Error"), "подключения"),
            (Exception("Unknown Error"), "непредвиденная ошибка"),
        ],
    )
    def test_get_error_message(self, error, expected_substring):
        """Тест получения сообщения для разных типов ошибок."""
        message = get_error_message(error)
        assert expected_substring in message

    def test_get_error_message_nested(self):
        """Тест получения сообщения для вложенных ошибок."""
        # Создаем вложенную ошибку
        original_error = ValueError("Original Error")
        nested_error = commands.CommandInvokeError(original_error)

        # Получаем сообщение
        message = get_error_message(nested_error)

        # Проверяем, что сообщение содержит информацию об оригинальной ошибке
        assert "значения" in message
        assert "Original Error" in message


class TestSafeSend:
    """Тесты для функции safe_send."""

    @pytest.mark.asyncio
    async def test_safe_send_context(self, mock_context):
        """Тест отправки сообщения в Context."""
        # Вызываем функцию
        result = await safe_send(mock_context, "Test message", embed=None)

        # Проверяем результат
        mock_context.send.assert_called_once_with(content="Test message", embed=None, delete_after=None)
        assert result == mock_context.send.return_value

    @pytest.mark.asyncio
    async def test_safe_send_interaction_not_done(self, mock_interaction):
        """Тест отправки сообщения в Interaction (response не выполнен)."""
        # Настраиваем мок
        mock_interaction.response.is_done.return_value = False

        # Вызываем функцию
        result = await safe_send(mock_interaction, "Test message", embed=None, ephemeral=True)

        # Проверяем результат
        mock_interaction.response.send_message.assert_called_once_with(
            content="Test message", embed=None, ephemeral=True
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_safe_send_interaction_done(self, mock_interaction):
        """Тест отправки сообщения в Interaction (response выполнен)."""
        # Настраиваем мок
        mock_interaction.response.is_done.return_value = True

        # Вызываем функцию
        result = await safe_send(mock_interaction, "Test message", embed=None, ephemeral=True)

        # Проверяем результат
        mock_interaction.followup.send.assert_called_once_with(
            content="Test message", embed=None, ephemeral=True
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_safe_send_exception(self, mock_context):
        """Тест обработки исключений."""
        # Настраиваем мок, чтобы он вызывал исключение
        mock_context.send.side_effect = Exception("Test exception")

        # Патчим логгер
        with patch("utils.error_handler.logger") as mock_logger:
            # Вызываем функцию
            result = await safe_send(mock_context, "Test message")

            # Проверяем результат
            assert result is None
            mock_logger.error.assert_called_once()
            assert "Test exception" in mock_logger.error.call_args[0][0]


class TestSafeSendError:
    """Тесты для функции safe_send_error."""

    @pytest.mark.asyncio
    async def test_safe_send_error(self, mock_context):
        """Тест отправки сообщения об ошибке."""
        # Патчим функцию safe_send
        with patch("utils.error_handler.safe_send") as mock_safe_send:
            # Вызываем функцию
            await safe_send_error(mock_context, "Test error")

            # Проверяем результат
            mock_safe_send.assert_called_once()
            assert mock_safe_send.call_args[1]["embed"] is not None
            assert mock_safe_send.call_args[1]["embed"].title == "❌ Ошибка"
            assert mock_safe_send.call_args[1]["embed"].description == "Test error"
            assert mock_safe_send.call_args[1]["ephemeral"] is True
