"""Тесты для handlers/events.py.

Музыкальные хелперы (``cleanup_player``/``auto_disconnect``) удалены — их
заменили слушатели wavelink в ``cogs/music.py``. Здесь остались тесты только
для жизненного цикла бота и обработчика ошибок префиксных команд.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands

from handlers.events import Events


class TestEventsInit:
    def test_events_init(self, mock_bot: MagicMock) -> None:
        events = Events(mock_bot)
        assert events.bot is mock_bot


class TestOnReady:
    @pytest.mark.asyncio
    async def test_on_ready_syncs_and_sets_presence(self, mock_bot: MagicMock) -> None:
        events = Events(mock_bot)
        mock_bot.tree.sync = AsyncMock(
            return_value=[MagicMock(name="cmd1"), MagicMock(name="cmd2")]
        )
        mock_bot.change_presence = AsyncMock()

        with patch("handlers.events.logger") as mock_logger:
            await events.on_ready()
            assert mock_logger.info.call_count >= 3
            mock_bot.tree.sync.assert_called_once()
            mock_bot.change_presence.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_ready_handles_sync_error(self, mock_bot: MagicMock) -> None:
        events = Events(mock_bot)
        mock_bot.tree.sync = AsyncMock(side_effect=Exception("Sync error"))
        mock_bot.change_presence = AsyncMock()

        with patch("handlers.events.logger") as mock_logger:
            await events.on_ready()
            mock_logger.error.assert_called_once()
            assert (
                "Не удалось синхронизировать команды"
                in mock_logger.error.call_args[0][0]
            )
            mock_bot.change_presence.assert_called_once()


class TestOnMemberRemove:
    @pytest.mark.asyncio
    async def test_sends_to_general(
        self, mock_bot: MagicMock, mock_member: MagicMock, mock_text_channel: MagicMock
    ) -> None:
        events = Events(mock_bot)
        mock_member.guild.text_channels = [mock_text_channel]
        mock_text_channel.name = "general"

        with patch("handlers.events.discord.utils.get", return_value=mock_text_channel):
            await events.on_member_remove(mock_member)
            mock_text_channel.send.assert_called_once()
            assert mock_member.name in mock_text_channel.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_fallback_when_no_general(
        self, mock_bot: MagicMock, mock_member: MagicMock, mock_text_channel: MagicMock
    ) -> None:
        events = Events(mock_bot)
        mock_member.guild.text_channels = [mock_text_channel]
        mock_text_channel.name = "not-general"
        mock_text_channel.permissions_for.return_value.send_messages = True

        with patch("handlers.events.discord.utils.get", return_value=None):
            await events.on_member_remove(mock_member)
            mock_text_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_swallows_errors(
        self, mock_bot: MagicMock, mock_member: MagicMock
    ) -> None:
        events = Events(mock_bot)
        mock_member.guild.text_channels = []

        with (
            patch("handlers.events.discord.utils.get", side_effect=Exception("boom")),
            patch("handlers.events.logger") as mock_logger,
        ):
            await events.on_member_remove(mock_member)
            mock_logger.error.assert_called_once()


class TestOnCommandError:
    @pytest.mark.asyncio
    async def test_command_not_found_silenced(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        await events.on_command_error(mock_context, commands.CommandNotFound())
        mock_context.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_required_argument(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        error = commands.MissingRequiredArgument(param=MagicMock(name="test_param"))
        await events.on_command_error(mock_context, error)
        mock_context.send.assert_called_once()
        assert "Отсутствует аргумент" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_bad_argument(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        await events.on_command_error(mock_context, commands.BadArgument())
        mock_context.send.assert_called_once()
        assert "Неверный аргумент" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_missing_permissions(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        await events.on_command_error(
            mock_context, commands.MissingPermissions(["manage_messages"])
        )
        mock_context.send.assert_called_once()
        assert "Нет прав" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_bot_missing_permissions(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        await events.on_command_error(
            mock_context, commands.BotMissingPermissions(["manage_messages"])
        )
        mock_context.send.assert_called_once()
        assert "У бота нет прав" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_command_on_cooldown(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        error = commands.CommandOnCooldown(
            cooldown=MagicMock(), retry_after=5.0, type=commands.BucketType.default
        )
        await events.on_command_error(mock_context, error)
        mock_context.send.assert_called_once()
        assert "Перезарядка" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_not_owner(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        await events.on_command_error(mock_context, commands.NotOwner())
        mock_context.send.assert_called_once()
        assert "Команда только для владельца" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_generic_error_logged_and_replied(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        mock_context.command = "test_command"

        with patch("handlers.events.logger") as mock_logger:
            await events.on_command_error(mock_context, Exception("Test error"))
            mock_logger.error.assert_called_once()
            mock_context.send.assert_called_once()
            assert "Произошла ошибка" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cog_command_error_delegates(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        error = commands.BadArgument()
        with patch.object(events, "on_command_error", AsyncMock()) as mock_handler:
            await events.cog_command_error(mock_context, error)
            mock_handler.assert_called_once_with(mock_context, error)


class TestSendError:
    @pytest.mark.asyncio
    async def test_sends_with_emoji(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        await events._send_error(mock_context, "Test")
        mock_context.send.assert_called_once()
        assert "❌ Test" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_swallows_send_error(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        mock_context.send.side_effect = Exception("Send error")
        with patch("handlers.events.logger") as mock_logger:
            await events._send_error(mock_context, "Test")
            mock_logger.error.assert_called_once()


class TestSetup:
    @pytest.mark.asyncio
    async def test_setup_registers_cog(self, mock_bot: MagicMock) -> None:
        from handlers.events import setup

        with patch.object(mock_bot, "add_cog", AsyncMock()) as mock_add_cog:
            await setup(mock_bot)
            mock_add_cog.assert_called_once()
