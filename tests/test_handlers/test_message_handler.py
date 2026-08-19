"""Тесты для handlers/message_handler.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from handlers.message_handler import MessageHandler


class TestMessageHandlerInit:
    """Тесты для инициализации MessageHandler."""

    def test_message_handler_init(self, mock_bot):
        """Тест инициализации MessageHandler."""
        handler = MessageHandler(mock_bot)
        assert handler.bot == mock_bot
        assert isinstance(handler.cooldowns, dict)
        assert len(handler.cooldowns) == 0


class TestMessageHandlerMethods:
    """Тесты для методов MessageHandler."""

    @pytest.mark.asyncio
    async def test_cog_unload(self, mock_bot):
        """Тест метода cog_unload."""
        handler = MessageHandler(mock_bot)
        
        # Патчим logger
        with patch("handlers.message_handler.logger") as mock_logger:
            # Вызываем метод
            await handler.cog_unload()
            
            # Проверяем, что logger.info был вызван
            mock_logger.info.assert_called_once()
            assert handler.__class__.__name__ in mock_logger.info.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cog_unload_waits_for_pending_stats_writes(self, mock_bot):
        """Выгрузка кога не теряет уже запущенную запись статистики."""
        handler = MessageHandler(mock_bot)
        allow_finish = asyncio.Event()

        async def pending_write() -> None:
            await allow_finish.wait()

        stats_task = asyncio.create_task(pending_write())
        handler._stats_tasks.add(stats_task)
        stats_task.add_done_callback(handler._on_stats_task_done)
        unload_task = asyncio.create_task(handler.cog_unload())
        await asyncio.sleep(0)

        assert not unload_task.done()
        allow_finish.set()
        await unload_task
        assert not handler._stats_tasks

    @pytest.mark.asyncio
    async def test_on_message_from_bot(self, mock_bot, mock_message):
        """Тест обработки сообщения от бота."""
        handler = MessageHandler(mock_bot)
        
        # Настраиваем моки
        mock_message.author.bot = True
        mock_bot.get_prefix = AsyncMock(return_value="!")
        
        # Вызываем метод
        await handler.on_message(mock_message)
        
        # Проверяем, что обработка была прервана (cooldowns не изменился)
        assert len(handler.cooldowns) == 0
        mock_bot.get_prefix.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_message_in_dm(self, mock_bot, mock_message):
        """Тест обработки личного сообщения."""
        handler = MessageHandler(mock_bot)
        
        # Настраиваем моки
        mock_message.author.bot = False
        mock_message.guild = None  # Личное сообщение
        mock_bot.get_prefix = AsyncMock(return_value="!")
        
        # Вызываем метод
        await handler.on_message(mock_message)
        
        # Проверяем, что обработка была прервана (cooldowns не изменился)
        assert len(handler.cooldowns) == 0
        mock_bot.get_prefix.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_message_command(self, mock_bot, mock_message):
        """Тест обработки сообщения с командой."""
        handler = MessageHandler(mock_bot)
        
        # Настраиваем моки
        mock_message.author.bot = False
        mock_message.content = "!test"
        mock_bot.get_prefix = AsyncMock(return_value="!")
        
        # Вызываем метод
        await handler.on_message(mock_message)
        
        # Проверяем, что обработка была прервана (cooldowns не изменился)
        assert len(handler.cooldowns) == 0

    @pytest.mark.asyncio
    async def test_on_message_command_multiple_prefixes(self, mock_bot, mock_message):
        """Тест обработки сообщения с командой при нескольких префиксах."""
        handler = MessageHandler(mock_bot)
        
        # Настраиваем моки
        mock_message.author.bot = False
        mock_message.content = "?test"
        mock_bot.get_prefix = AsyncMock(return_value=["!", "?", "/"])
        
        # Вызываем метод
        await handler.on_message(mock_message)
        
        # Проверяем, что обработка была прервана (cooldowns не изменился)
        assert len(handler.cooldowns) == 0

    @pytest.mark.asyncio
    async def test_on_message_cooldown(self, mock_bot, mock_message):
        """Тест кулдауна при обработке сообщений."""
        handler = MessageHandler(mock_bot)
        
        # Настраиваем моки
        mock_message.author.bot = False
        mock_message.author.id = 123456789
        mock_message.content = "Тестовое сообщение"
        mock_bot.get_prefix = AsyncMock(return_value="!")
        
        # Устанавливаем кулдаун
        current_time = asyncio.get_event_loop().time()
        handler.cooldowns[mock_message.author.id] = current_time
        
        # Патчим handle_message
        with patch("utils.message_utils.handle_message", AsyncMock()) as mock_handle_message:
            # Вызываем метод
            await handler.on_message(mock_message)
            
            # Проверяем, что handle_message не был вызван из-за кулдауна
            mock_handle_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_message_valid(self, mock_bot, mock_message):
        """Тест обработки обычного сообщения."""
        handler = MessageHandler(mock_bot)
        
        # Настраиваем моки
        mock_message.author.bot = False
        mock_message.author.id = 123456789
        mock_message.content = "Тестовое сообщение"
        mock_bot.get_prefix = AsyncMock(return_value="!")
        
        # Патчим handle_message и time.monotonic
        with patch("utils.message_utils.handle_message", AsyncMock()) as mock_handle_message, \
             patch("handlers.message_handler.time.monotonic", return_value=100.0):
            
            # Вызываем метод
            await handler.on_message(mock_message)
            
            # Проверяем, что handle_message был вызван
            mock_handle_message.assert_called_once_with(mock_message)
            
            # Проверяем, что кулдаун был установлен
            assert mock_message.author.id in handler.cooldowns
            assert handler.cooldowns[mock_message.author.id] == 100.0

    @pytest.mark.asyncio
    async def test_on_message_error(self, mock_bot, mock_message):
        """Тест обработки ошибки при обработке сообщения."""
        handler = MessageHandler(mock_bot)
        
        # Настраиваем моки
        mock_message.author.bot = False
        mock_message.author.id = 123456789
        mock_message.content = "Тестовое сообщение"
        mock_bot.get_prefix = AsyncMock(return_value="!")
        
        # Патчим handle_message, чтобы вызвать исключение
        with patch("utils.message_utils.handle_message",
                  AsyncMock(side_effect=Exception("Test error"))), \
             patch("handlers.message_handler.logger") as mock_logger, \
             patch("asyncio.get_event_loop") as mock_get_loop:
            
            # Настраиваем мок для времени
            mock_loop = MagicMock()
            mock_loop.time.return_value = 100.0
            mock_get_loop.return_value = mock_loop
            
            # Вызываем метод
            await handler.on_message(mock_message)
            
            # Проверяем, что logger.error был вызван
            mock_logger.error.assert_called_once()
            assert "Ошибка при обработке сообщения" in mock_logger.error.call_args[0][0]

class TestSetup:
    """Тесты для функции setup."""

    @pytest.mark.asyncio
    async def test_setup(self, mock_bot):
        """Тест функции setup."""
        from handlers.message_handler import setup
        
        # Патчим add_cog и logger
        with patch.object(mock_bot, "add_cog", AsyncMock()) as mock_add_cog, \
             patch("handlers.message_handler.logger") as mock_logger:
            
            # Вызываем функцию
            await setup(mock_bot)
            
            # Проверяем, что add_cog был вызван
            mock_add_cog.assert_called_once()
            
            # Проверяем, что logger.info был вызван
            mock_logger.info.assert_called_once()
            assert "Ког MessageHandler добавлен" in mock_logger.info.call_args[0][0]
