"""Тесты для handlers/events.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from handlers.events import Events, cleanup_player, auto_disconnect


class TestEventsInit:
    """Тесты для инициализации Events."""

    def test_events_init(self, mock_bot):
        """Тест инициализации Events."""
        events = Events(mock_bot)
        assert events.bot == mock_bot


class TestEventHandlers:
    """Тесты для обработчиков событий."""

    @pytest.mark.asyncio
    async def test_on_ready(self, mock_bot):
        """Тест обработчика on_ready."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Настраиваем моки
        mock_bot.tree.sync = AsyncMock(return_value=[
            MagicMock(name="cmd1"),
            MagicMock(name="cmd2")
        ])
        mock_bot.change_presence = AsyncMock()
        
        # Патчим logger
        with patch("handlers.events.logger") as mock_logger:
            # Вызываем обработчик
            await events.on_ready()
            
            # Проверяем, что logger.info был вызван
            assert mock_logger.info.call_count >= 3
            mock_logger.info.assert_any_call(f"Бот {mock_bot.user.name} (ID: {mock_bot.user.id}) готов к работе.")
            
            # Проверяем, что sync был вызван
            mock_bot.tree.sync.assert_called_once()
            
            # Проверяем, что change_presence был вызван
            mock_bot.change_presence.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_ready_sync_error(self, mock_bot):
        """Тест обработчика on_ready при ошибке синхронизации команд."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Настраиваем моки
        mock_bot.tree.sync = AsyncMock(side_effect=Exception("Sync error"))
        mock_bot.change_presence = AsyncMock()
        
        # Патчим logger
        with patch("handlers.events.logger") as mock_logger:
            # Вызываем обработчик
            await events.on_ready()
            
            # Проверяем, что logger.error был вызван
            mock_logger.error.assert_called_once()
            assert "Не удалось синхронизировать команды" in mock_logger.error.call_args[0][0]
            
            # Проверяем, что change_presence был вызван несмотря на ошибку
            mock_bot.change_presence.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_member_remove(self, mock_bot, mock_member, mock_text_channel):
        """Тест обработчика on_member_remove."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Настраиваем моки
        mock_member.guild.text_channels = [mock_text_channel]
        mock_text_channel.name = "general"
        
        # Патчим discord.utils.get
        with patch("handlers.events.discord.utils.get", return_value=mock_text_channel):
            # Вызываем обработчик
            await events.on_member_remove(mock_member)
            
            # Проверяем, что send был вызван с правильными аргументами
            mock_text_channel.send.assert_called_once()
            assert mock_member.name in mock_text_channel.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_member_remove_no_general(self, mock_bot, mock_member, mock_text_channel):
        """Тест обработчика on_member_remove при отсутствии канала #general."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Настраиваем моки
        mock_member.guild.text_channels = [mock_text_channel]
        mock_text_channel.name = "not-general"
        mock_text_channel.permissions_for.return_value.send_messages = True
        
        # Патчим discord.utils.get
        with patch("handlers.events.discord.utils.get", return_value=None):
            # Вызываем обработчик
            await events.on_member_remove(mock_member)
            
            # Проверяем, что send был вызван с правильными аргументами
            mock_text_channel.send.assert_called_once()
            assert mock_member.name in mock_text_channel.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_member_remove_error(self, mock_bot, mock_member):
        """Тест обработчика on_member_remove при возникновении ошибки."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Настраиваем моки
        mock_member.guild.text_channels = []
        
        # Патчим discord.utils.get, чтобы вызвать исключение
        with patch("handlers.events.discord.utils.get", side_effect=Exception("Test error")), \
             patch("handlers.events.logger") as mock_logger:
            # Вызываем обработчик
            await events.on_member_remove(mock_member)
            
            # Проверяем, что logger.error был вызван
            mock_logger.error.assert_called_once()
            assert "Ошибка в on_member_remove" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_voice_state_update_same_channel(self, mock_bot, mock_member):
        """Тест обработчика on_voice_state_update при неизменном канале."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем моки голосовых состояний
        before = MagicMock(spec=discord.VoiceState)
        after = MagicMock(spec=discord.VoiceState)
        before.channel = after.channel = MagicMock(spec=discord.VoiceChannel)
        
        # Вызываем обработчик
        await events.on_voice_state_update(mock_member, before, after)
        
        # Проверяем, что функция завершилась без ошибок
        # (нет дополнительных проверок, так как функция должна просто вернуться)

    @pytest.mark.asyncio
    async def test_on_voice_state_update_bot_disconnect(self, mock_bot, mock_member, mock_voice_channel):
        """Тест обработчика on_voice_state_update при отключении бота."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Настраиваем моки
        mock_member.id = mock_bot.user.id  # Это бот
        mock_member.guild.name = "Test Guild"
        
        # Создаем моки голосовых состояний
        before = MagicMock(spec=discord.VoiceState)
        after = MagicMock(spec=discord.VoiceState)
        before.channel = mock_voice_channel
        after.channel = None
        
        # Создаем мок плеера
        mock_player = MagicMock()
        mock_music_cog = MagicMock()
        mock_music_cog.player = mock_player
        
        # Создаем класс MusicPlayer
        MockMusicPlayer = type("MusicPlayer", (), {})
        
        # Настраиваем player, чтобы он был экземпляром MusicPlayer
        mock_player.__class__ = MockMusicPlayer
        
        # Патчим get_cog, cleanup_player и другие зависимости
        with patch.object(mock_bot, "get_cog", return_value=mock_music_cog), \
             patch("handlers.events.cleanup_player", AsyncMock()) as mock_cleanup, \
             patch("handlers.events.MusicPlayer", MockMusicPlayer), \
             patch("handlers.events.auto_disconnect", AsyncMock()):
            
            # Вызываем обработчик
            await events.on_voice_state_update(mock_member, before, after)
            
            # Проверяем, что cleanup_player был вызван
            mock_cleanup.assert_called_once_with(mock_player, mock_member.guild.name)

    @pytest.mark.asyncio
    async def test_on_voice_state_update_user_leave(self, mock_bot, mock_member, mock_voice_channel, mock_guild):
        """Тест обработчика on_voice_state_update при выходе пользователя."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Настраиваем моки
        mock_member.id = 987654321  # Не бот
        mock_member.bot = False
        mock_member.guild = mock_guild
        
        # Создаем моки голосовых состояний
        before = MagicMock(spec=discord.VoiceState)
        after = MagicMock(spec=discord.VoiceState)
        before.channel = mock_voice_channel
        after.channel = None
        
        # Настраиваем voice_client
        mock_voice_client = MagicMock(spec=discord.VoiceClient)
        mock_voice_client.channel = mock_voice_channel
        mock_voice_client.channel.members = [mock_bot.user]  # Только бот остался
        mock_guild.voice_client = mock_voice_client
        
        # Создаем мок плеера
        mock_player = MagicMock()
        mock_music_cog = MagicMock()
        mock_music_cog.player = mock_player
        
        # Создаем класс MusicPlayer
        MockMusicPlayer = type("MusicPlayer", (), {})
        
        # Настраиваем player, чтобы он был экземпляром MusicPlayer
        mock_player.__class__ = MockMusicPlayer
        
        # Патчим get_cog, auto_disconnect и другие зависимости
        with patch.object(mock_bot, "get_cog", return_value=mock_music_cog), \
             patch("handlers.events.auto_disconnect", AsyncMock()) as mock_auto_disconnect, \
             patch("handlers.events.MusicPlayer", MockMusicPlayer), \
             patch("handlers.events.cleanup_player", AsyncMock()), \
             patch("handlers.events.asyncio.sleep", AsyncMock()):
            
            # Вызываем обработчик
            await events.on_voice_state_update(mock_member, before, after)
            
            # Проверяем, что auto_disconnect был вызван
            mock_auto_disconnect.assert_called_once_with(mock_player, mock_member.guild, before.channel)

    @pytest.mark.asyncio
    async def test_on_command_error_command_not_found(self, mock_bot, mock_context):
        """Тест обработчика on_command_error для CommandNotFound."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку
        error = commands.CommandNotFound()
        
        # Вызываем обработчик
        await events.on_command_error(mock_context, error)
        
        # Проверяем, что ctx.send не был вызван
        mock_context.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_command_error_missing_required_argument(self, mock_bot, mock_context):
        """Тест обработчика on_command_error для MissingRequiredArgument."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку
        error = commands.MissingRequiredArgument(param=MagicMock(name="test_param"))
        
        # Вызываем обработчик
        await events.on_command_error(mock_context, error)
        
        # Проверяем, что ctx.send был вызван с правильным сообщением
        mock_context.send.assert_called_once()
        assert "Отсутствует аргумент" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_command_error_bad_argument(self, mock_bot, mock_context):
        """Тест обработчика on_command_error для BadArgument."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку
        error = commands.BadArgument()
        
        # Вызываем обработчик
        await events.on_command_error(mock_context, error)
        
        # Проверяем, что ctx.send был вызван с правильным сообщением
        mock_context.send.assert_called_once()
        assert "Неверный аргумент" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_command_error_missing_permissions(self, mock_bot, mock_context):
        """Тест обработчика on_command_error для MissingPermissions."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку
        error = commands.MissingPermissions(["manage_messages"])
        
        # Вызываем обработчик
        await events.on_command_error(mock_context, error)
        
        # Проверяем, что ctx.send был вызван с правильным сообщением
        mock_context.send.assert_called_once()
        assert "Нет прав" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_command_error_bot_missing_permissions(self, mock_bot, mock_context):
        """Тест обработчика on_command_error для BotMissingPermissions."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку
        error = commands.BotMissingPermissions(["manage_messages"])
        
        # Вызываем обработчик
        await events.on_command_error(mock_context, error)
        
        # Проверяем, что ctx.send был вызван с правильным сообщением
        mock_context.send.assert_called_once()
        assert "У бота нет прав" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_command_error_command_on_cooldown(self, mock_bot, mock_context):
        """Тест обработчика on_command_error для CommandOnCooldown."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку с правильными аргументами
        error = commands.CommandOnCooldown(cooldown=MagicMock(), retry_after=5.0, type=commands.BucketType.default)
        
        # Вызываем обработчик
        await events.on_command_error(mock_context, error)
        
        # Проверяем, что ctx.send был вызван с правильным сообщением
        mock_context.send.assert_called_once()
        assert "Перезарядка" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_command_error_not_owner(self, mock_bot, mock_context):
        """Тест обработчика on_command_error для NotOwner."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку
        error = commands.NotOwner()
        
        # Вызываем обработчик
        await events.on_command_error(mock_context, error)
        
        # Проверяем, что ctx.send был вызван с правильным сообщением
        mock_context.send.assert_called_once()
        assert "Команда только для владельца" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_command_error_generic(self, mock_bot, mock_context):
        """Тест обработчика on_command_error для общей ошибки."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку
        error = Exception("Test error")
        
        # Настраиваем mock_context
        mock_context.command = "test_command"
        
        # Патчим logger
        with patch("handlers.events.logger") as mock_logger:
            # Вызываем обработчик
            await events.on_command_error(mock_context, error)
            
            # Проверяем, что logger.error был вызван
            mock_logger.error.assert_called_once()
            
            # Проверяем, что ctx.send был вызван с правильным сообщением
            mock_context.send.assert_called_once()
            assert "Произошла ошибка" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cog_command_error(self, mock_bot, mock_context):
        """Тест метода cog_command_error."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Создаем ошибку
        error = commands.BadArgument()
        
        # Патчим on_command_error
        with patch.object(events, "on_command_error", AsyncMock()) as mock_on_command_error:
            # Вызываем метод
            await events.cog_command_error(mock_context, error)
            
            # Проверяем, что on_command_error был вызван с правильными аргументами
            mock_on_command_error.assert_called_once_with(mock_context, error)

    @pytest.mark.asyncio
    async def test_send_error(self, mock_bot, mock_context):
        """Тест метода _send_error."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Вызываем метод
        await events._send_error(mock_context, "Test error message")
        
        # Проверяем, что ctx.send был вызван с правильным сообщением
        mock_context.send.assert_called_once()
        assert "❌ Test error message" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_send_error_exception(self, mock_bot, mock_context):
        """Тест метода _send_error при возникновении исключения."""
        # Создаем экземпляр Events
        events = Events(mock_bot)
        
        # Настраиваем мок
        mock_context.send.side_effect = Exception("Send error")
        
        # Патчим logger
        with patch("handlers.events.logger") as mock_logger:
            # Вызываем метод
            await events._send_error(mock_context, "Test error message")
            
            # Проверяем, что logger.error был вызван
            mock_logger.error.assert_called_once()
            assert "Не удалось отправить сообщение" in mock_logger.error.call_args[0][0]


class TestHelperFunctions:
    """Тесты для вспомогательных функций."""

    @pytest.mark.asyncio
    async def test_cleanup_player(self):
        """Тест функции cleanup_player."""
        # Создаем мок плеера
        mock_player = MagicMock()
        mock_player.cleanup = AsyncMock()
        
        # Патчим logger
        with patch("handlers.events.logger") as mock_logger:
            # Вызываем функцию
            await cleanup_player(mock_player, "Test Guild")
            
            # Проверяем, что player.cleanup был вызван
            mock_player.cleanup.assert_called_once_with(clear_queue=True)
            
            # Проверяем, что logger.info был вызван
            mock_logger.info.assert_called_once()
            assert "Плеер очищен" in mock_logger.info.call_args[0][0]

    @pytest.mark.asyncio
    async def test_auto_disconnect(self, mock_guild, mock_voice_channel):
        """Тест функции auto_disconnect."""
        # Создаем мок плеера
        mock_player = MagicMock()
        mock_player.disconnect = AsyncMock()
        
        # Настраиваем моки
        mock_voice_client = MagicMock(spec=discord.VoiceClient)
        mock_voice_client.channel = mock_voice_channel
        mock_voice_client.channel.members = [MagicMock()]  # Только бот в канале
        mock_guild.voice_client = mock_voice_client
        
        # Патчим logger и asyncio.sleep
        with patch("handlers.events.logger") as mock_logger, \
             patch("handlers.events.asyncio.sleep", AsyncMock()):
            
            # Вызываем функцию
            await auto_disconnect(mock_player, mock_guild, mock_voice_channel)
            
            # Проверяем, что player.disconnect был вызван
            mock_player.disconnect.assert_called_once()
            
            # Проверяем, что logger.info был вызван
            assert mock_logger.info.call_count >= 2
            mock_logger.info.assert_any_call(f"Запущено автоотключение для {mock_guild.name} из канала {mock_voice_channel.name}")

    @pytest.mark.asyncio
    async def test_auto_disconnect_not_empty(self, mock_guild, mock_voice_channel):
        """Тест функции auto_disconnect, когда канал не пуст."""
        # Создаем мок плеера
        mock_player = MagicMock()
        mock_player.disconnect = AsyncMock()
        
        # Настраиваем моки
        mock_voice_client = MagicMock(spec=discord.VoiceClient)
        mock_voice_client.channel = mock_voice_channel
        mock_voice_client.channel.members = [MagicMock(), MagicMock()]  # Бот и еще кто-то
        mock_guild.voice_client = mock_voice_client
        
        # Патчим logger и asyncio.sleep
        with patch("handlers.events.logger") as mock_logger, \
             patch("handlers.events.asyncio.sleep", AsyncMock()):
            
            # Вызываем функцию
            await auto_disconnect(mock_player, mock_guild, mock_voice_channel)
            
            # Проверяем, что player.disconnect не был вызван
            mock_player.disconnect.assert_not_called()


class TestSetup:
    """Тесты для функции setup."""

    @pytest.mark.asyncio
    async def test_setup(self, mock_bot):
        """Тест функции setup."""
        from handlers.events import setup
        
        # Патчим add_cog и logger
        with patch.object(mock_bot, "add_cog", AsyncMock()) as mock_add_cog, \
             patch("handlers.events.logger") as mock_logger:
            
            # Вызываем функцию
            await setup(mock_bot)
            
            # Проверяем, что add_cog был вызван
            mock_add_cog.assert_called_once()
            
            # Проверяем, что logger.info был вызван
            mock_logger.info.assert_called_once()
            assert "Ког Events добавлен" in mock_logger.info.call_args[0][0]
