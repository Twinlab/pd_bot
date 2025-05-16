from unittest.mock import MagicMock

import discord
import pytest

from cogs.links import LinksCog


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot


@pytest.fixture
def links_cog(mock_bot):
    return LinksCog(mock_bot)


def test_links_cog_init(links_cog):
    assert isinstance(links_cog, LinksCog)
    assert hasattr(links_cog, "bot")


@pytest.mark.asyncio
async def test_links_cog_registers_commands(links_cog):
    commands = [cmd.name for cmd in links_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
