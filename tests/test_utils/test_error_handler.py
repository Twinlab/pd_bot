"""Тесты для модуля error_handler."""

from unittest.mock import MagicMock, patch

import discord
import pytest
from discord.ext import commands

from discord import app_commands

from utils.error_handler import (
    command_error_handler,
    get_error_message,
    handle_app_command_error,
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

    @pytest.mark.asyncio
    async def test_command_error_handler_swallows_unknown_exception(self):
        """Декоратор должен проглатывать исключения после ответа юзеру.

        Иначе discord.py обернёт их в CommandInvokeError и вторично дёрнет
        ``on_command_error`` в handlers/events.py — получим двойной лог
        и второй embed «Произошла непредвиденная ошибка» в чат.
        """

        class CustomBoom(Exception):
            """Что-то неожиданное, чего нет в ERROR_MESSAGES."""

        async def mock_command(self, ctx, *args, **kwargs):
            raise CustomBoom("boom")

        decorated = command_error_handler(mock_command)

        self_mock = MagicMock()
        self_mock.bot = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.command = MagicMock()
        ctx_mock.command.name = "test_command"

        with (
            patch("utils.error_handler.safe_send_error") as mock_safe_send_error,
            patch("utils.error_handler.logger") as mock_logger,
        ):
            result = await decorated(self_mock, ctx_mock)

        # Исключение проглочено — функция возвращает None, не падает.
        assert result is None
        # Юзер всё равно получил уведомление, лог со стеком тоже есть.
        mock_safe_send_error.assert_called_once()
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_error_handler_propagates_system_exit(self):
        """SystemExit / KeyboardInterrupt должны пробрасываться (завершают процесс)."""

        async def mock_command(self, ctx, *args, **kwargs):
            raise KeyboardInterrupt

        decorated = command_error_handler(mock_command)

        self_mock = MagicMock()
        self_mock.bot = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.command = MagicMock()
        ctx_mock.command.name = "test_command"

        with (
            patch("utils.error_handler.safe_send_error"),
            patch("utils.error_handler.logger"),
            pytest.raises(KeyboardInterrupt),
        ):
            await decorated(self_mock, ctx_mock)

    @pytest.mark.asyncio
    async def test_command_error_handler_known_error_is_swallowed(self):
        """А известные ошибки из ERROR_MESSAGES по-прежнему НЕ пробрасываются."""

        async def mock_command(self, ctx, *args, **kwargs):
            raise commands.BadArgument("плохой аргумент")

        decorated = command_error_handler(mock_command)

        self_mock = MagicMock()
        self_mock.bot = MagicMock()
        ctx_mock = MagicMock()
        ctx_mock.command = MagicMock()
        ctx_mock.command.name = "test_command"

        with (
            patch("utils.error_handler.safe_send_error") as mock_safe_send_error,
            patch("utils.error_handler.logger"),
        ):
            # Не должно бросить — известная ошибка.
            result = await decorated(self_mock, ctx_mock)

        assert result is None
        mock_safe_send_error.assert_called_once()


class TestHandleAppCommandError:
    """Тесты для глобального обработчика ошибок slash-команд."""

    @pytest.mark.asyncio
    async def test_known_error_no_stack_log(self, mock_interaction):
        """Штатная ошибка (нет прав) → ephemeral-ответ, без лога со стеком."""
        error = app_commands.MissingPermissions(["administrator"])
        with patch("utils.error_handler.logger") as mock_logger:
            await handle_app_command_error(mock_interaction, error)

        mock_logger.error.assert_not_called()
        mock_interaction.response.send_message.assert_awaited_once()
        kwargs = mock_interaction.response.send_message.await_args.kwargs
        assert kwargs["ephemeral"] is True
        assert "недостаточно прав" in kwargs["embed"].description

    @pytest.mark.asyncio
    async def test_unknown_error_logged_with_stack(self, mock_interaction):
        """Незнакомая ошибка логируется со стеком и тоже уходит юзеру."""
        error = app_commands.CommandInvokeError(MagicMock(), ValueError("boom"))
        with patch("utils.error_handler.logger") as mock_logger:
            await handle_app_command_error(mock_interaction, error)

        mock_logger.error.assert_called_once()
        assert mock_logger.error.call_args.kwargs.get("exc_info") is error
        mock_interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_followup_when_response_done(self, mock_interaction):
        """Если интеракция уже отвечена — отвечаем через followup."""
        mock_interaction.response.is_done.return_value = True
        error = app_commands.CheckFailure()
        with patch("utils.error_handler.logger"):
            await handle_app_command_error(mock_interaction, error)

        mock_interaction.followup.send.assert_awaited_once()
        mock_interaction.response.send_message.assert_not_called()


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
            (discord.Forbidden(MagicMock(), "Forbidden"), "нет прав"),
            (discord.NotFound(MagicMock(), "Not Found"), "не найден"),
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
        mock_context.send.assert_called_once_with(
            content="Test message", embed=None, delete_after=None, ephemeral=False
        )
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
