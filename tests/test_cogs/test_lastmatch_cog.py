"""Тесты для кога LastMatchCog."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.lastmatch import LastMatchCog


@pytest.fixture
def mock_context(mock_bot):
    """Создает мок контекста команды."""
    ctx = MagicMock(spec=commands.Context)
    ctx.bot = mock_bot
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 123456789
    ctx.author.mention = "<@123456789>"
    ctx.send = AsyncMock()
    ctx.defer = AsyncMock()
    return ctx


@pytest.fixture
def mock_member():
    """Создает мок участника Discord."""
    member = MagicMock(spec=discord.Member)
    member.id = 987654321
    member.mention = "<@987654321>"
    return member


@pytest.fixture
def lastmatch_cog(mock_bot):
    """Создает экземпляр LastMatchCog с замоканным LinksDataManager."""
    with patch("cogs.lastmatch.LinksDataManager") as mock_mgr_cls:
        mock_mgr = MagicMock()
        mock_mgr.get_links = AsyncMock()
        mock_mgr_cls.return_value = mock_mgr
        cog = LastMatchCog(mock_bot)
    return cog


class TestLastMatchCogInit:
    """Тесты инициализации кога."""

    def test_lastmatch_cog_init(self, lastmatch_cog, mock_bot):
        """Тест корректной инициализации кога."""
        assert isinstance(lastmatch_cog, LastMatchCog)
        assert lastmatch_cog.bot == mock_bot
        # LinksDataManager должен быть создан прямо в коге — без обращений к bot.get_cog().
        assert lastmatch_cog.links_manager is not None

    def test_lastmatch_cog_registers_commands(self, lastmatch_cog):
        """Тест регистрации команд кога."""
        commands_list = [cmd.name for cmd in lastmatch_cog.get_commands()]
        assert "lastmatch" in commands_list


class TestLastMatchCommand:
    """Тесты команды lastmatch."""

    @pytest.mark.asyncio
    async def test_lastmatch_links_manager_exception(self, lastmatch_cog, mock_context):
        """Тест обработки исключения при вызове links_manager.get_links."""
        lastmatch_cog.links_manager.get_links.side_effect = Exception("Database error")

        with patch("cogs.lastmatch.safe_send_error", new_callable=AsyncMock) as mock_safe_send:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)

            mock_safe_send.assert_awaited_once()
            error_arg = mock_safe_send.await_args.args[1]
            assert "Ошибка при получении привязанных аккаунтов" in str(error_arg)

    @pytest.mark.asyncio
    async def test_lastmatch_successful_self(self, lastmatch_cog, mock_context):
        """Тест успешного выполнения команды для себя."""
        lastmatch_cog.links_manager.get_links.return_value = [12345, 67890]

        with patch("cogs.lastmatch.handle_lastmatch", new_callable=AsyncMock) as mock_handle:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)

            mock_context.defer.assert_called_once()
            mock_handle.assert_awaited_once_with(mock_context, [12345, 67890], None)

    @pytest.mark.asyncio
    async def test_lastmatch_successful_other_member(self, lastmatch_cog, mock_context, mock_member):
        """Тест успешного выполнения команды для другого пользователя."""
        lastmatch_cog.links_manager.get_links.return_value = [54321]

        with patch("cogs.lastmatch.handle_lastmatch", new_callable=AsyncMock) as mock_handle:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context, mock_member)

            mock_context.defer.assert_called_once()
            lastmatch_cog.links_manager.get_links.assert_awaited_once_with(mock_member.id)
            mock_handle.assert_awaited_once_with(mock_context, [54321], mock_member)

    @pytest.mark.asyncio
    async def test_lastmatch_empty_links_list(self, lastmatch_cog, mock_context):
        """Тест когда список привязок пуст."""
        lastmatch_cog.links_manager.get_links.return_value = []

        with patch("cogs.lastmatch.handle_lastmatch", new_callable=AsyncMock) as mock_handle:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)

            mock_context.defer.assert_called_once()
            mock_handle.assert_awaited_once_with(mock_context, [], None)


class TestSetupFunction:
    """Тесты функции setup."""

    @pytest.mark.asyncio
    async def test_setup_function(self, mock_bot):
        """Тест функции setup кога."""
        from cogs.lastmatch import setup

        with patch("cogs.lastmatch.logger") as mock_logger:
            await setup(mock_bot)

            mock_bot.add_cog.assert_called_once()
            added_cog = mock_bot.add_cog.call_args[0][0]
            assert isinstance(added_cog, LastMatchCog)
            assert added_cog.bot == mock_bot

            mock_logger.info.assert_called_once_with("Ког LastMatchCog успешно загружен.")


class TestCommandDecorators:
    """Тесты декораторов команды."""

    def test_lastmatch_command_is_hybrid(self, lastmatch_cog):
        """Тест что команда lastmatch является hybrid командой."""
        lastmatch_command = None
        for cmd in lastmatch_cog.get_commands():
            if cmd.name == "lastmatch":
                lastmatch_command = cmd
                break

        assert lastmatch_command is not None
        assert hasattr(lastmatch_command, "app_command")

    def test_lastmatch_command_has_error_handler(self, lastmatch_cog):
        """Тест что команда lastmatch имеет обработчик ошибок."""
        lastmatch_command = None
        for cmd in lastmatch_cog.get_commands():
            if cmd.name == "lastmatch":
                lastmatch_command = cmd
                break

        assert lastmatch_command is not None
        # Проверяем что команда обернута декоратором command_error_handler.
        assert hasattr(lastmatch_command.callback, "__wrapped__")
