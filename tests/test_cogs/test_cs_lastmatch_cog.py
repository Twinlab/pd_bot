"""Тесты для CsLastMatchCog — команда /cslastmatch."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.cs_lastmatch import CsLastMatchCog


@pytest.fixture
def mock_links_manager():
    """Создаёт мок менеджера CS-привязок."""
    manager = MagicMock()
    manager.get_links = AsyncMock()
    return manager


@pytest.fixture
def cs_lastmatch_cog(mock_bot, mock_links_manager):
    """Создаёт экземпляр CsLastMatchCog с мок-зависимостями."""
    cog = CsLastMatchCog(mock_bot)
    cog.links_manager = mock_links_manager
    return cog


class TestInit:
    """Тесты инициализации."""

    def test_init(self, mock_bot):
        cog = CsLastMatchCog(mock_bot)
        assert isinstance(cog, CsLastMatchCog)
        assert cog.bot == mock_bot

    def test_registers_command(self, cs_lastmatch_cog):
        names = {cmd.name for cmd in cs_lastmatch_cog.get_commands()}
        assert "cslastmatch" in names


class TestCsLastMatch:
    """Тесты команды cslastmatch."""

    @pytest.mark.asyncio
    async def test_calls_handler(self, cs_lastmatch_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.defer = AsyncMock()
        links = [MagicMock()]
        mock_links_manager.get_links.return_value = links

        with patch("cogs.cs_lastmatch.handle_cs_lastmatch", new_callable=AsyncMock) as mock_handle:
            await cs_lastmatch_cog.cslastmatch.callback(cs_lastmatch_cog, mock_context)

        mock_links_manager.get_links.assert_awaited_once_with(1)
        mock_context.defer.assert_awaited_once()
        mock_handle.assert_awaited_once_with(mock_context, links, None)

    @pytest.mark.asyncio
    async def test_for_member(
        self, cs_lastmatch_cog, mock_context, mock_member, mock_links_manager
    ):
        mock_context.defer = AsyncMock()
        links = [MagicMock()]
        mock_links_manager.get_links.return_value = links

        with patch("cogs.cs_lastmatch.handle_cs_lastmatch", new_callable=AsyncMock) as mock_handle:
            await cs_lastmatch_cog.cslastmatch.callback(cs_lastmatch_cog, mock_context, mock_member)

        mock_links_manager.get_links.assert_awaited_once_with(mock_member.id)
        mock_handle.assert_awaited_once_with(mock_context, links, mock_member)

    @pytest.mark.asyncio
    async def test_manager_error(self, cs_lastmatch_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.defer = AsyncMock()
        mock_links_manager.get_links.side_effect = RuntimeError("db down")

        with (
            patch("cogs.cs_lastmatch.handle_cs_lastmatch", new_callable=AsyncMock) as mock_handle,
            patch("cogs.cs_lastmatch.safe_send_error", new_callable=AsyncMock) as mock_err,
        ):
            await cs_lastmatch_cog.cslastmatch.callback(cs_lastmatch_cog, mock_context)

        mock_err.assert_awaited_once()
        mock_handle.assert_not_called()


class TestLifecycle:
    """Тесты жизненного цикла кога."""

    @pytest.mark.asyncio
    async def test_cog_unload(self, cs_lastmatch_cog):
        await cs_lastmatch_cog.cog_unload()

    @pytest.mark.asyncio
    async def test_setup(self, mock_bot):
        from cogs.cs_lastmatch import setup

        mock_bot.add_cog = AsyncMock()
        await setup(mock_bot)
        added = mock_bot.add_cog.call_args[0][0]
        assert isinstance(added, CsLastMatchCog)
