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
    """Глобальный обработчик ошибок префиксных команд."""

    @pytest.mark.asyncio
    async def test_command_not_found_silenced(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        with patch("handlers.events.safe_send_error", AsyncMock()) as mock_send:
            await events.on_command_error(mock_context, commands.CommandNotFound())
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_known_error_uses_safe_send_error(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        """Известная ошибка → safe_send_error с текстом из ERROR_MESSAGES."""
        events = Events(mock_bot)
        with patch("handlers.events.safe_send_error", AsyncMock()) as mock_send:
            await events.on_command_error(mock_context, commands.BadArgument())
            mock_send.assert_awaited_once()
            sent_message = mock_send.await_args.args[1]
            assert "Неверный аргумент" in sent_message

    @pytest.mark.asyncio
    async def test_missing_permissions(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        events = Events(mock_bot)
        with patch("handlers.events.safe_send_error", AsyncMock()) as mock_send:
            await events.on_command_error(
                mock_context, commands.MissingPermissions(["manage_messages"])
            )
            mock_send.assert_awaited_once()
            assert "недостаточно прав" in mock_send.await_args.args[1]

    @pytest.mark.asyncio
    async def test_generic_error_logged_and_replied(
        self, mock_bot: MagicMock, mock_context: MagicMock
    ) -> None:
        """Неизвестная ошибка логируется со стеком и тоже идёт через safe_send_error."""
        events = Events(mock_bot)
        mock_context.command = "test_command"

        with (
            patch("handlers.events.logger") as mock_logger,
            patch("handlers.events.safe_send_error", AsyncMock()) as mock_send,
        ):
            await events.on_command_error(mock_context, Exception("Test error"))
            mock_logger.error.assert_called_once()
            mock_send.assert_awaited_once()


class TestSetup:
    @pytest.mark.asyncio
    async def test_setup_registers_cog(self, mock_bot: MagicMock) -> None:
        from handlers.events import setup

        with patch.object(mock_bot, "add_cog", AsyncMock()) as mock_add_cog:
            await setup(mock_bot)
            mock_add_cog.assert_called_once()
