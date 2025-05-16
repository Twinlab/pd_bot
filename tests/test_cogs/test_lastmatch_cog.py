from unittest.mock import MagicMock

import discord
import pytest

from cogs.lastmatch import LastMatchCog


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot


@pytest.fixture
def lastmatch_cog(mock_bot):
    return LastMatchCog(mock_bot)


def test_lastmatch_cog_init(lastmatch_cog):
    assert isinstance(lastmatch_cog, LastMatchCog)
    assert hasattr(lastmatch_cog, "bot")


@pytest.mark.asyncio
async def test_lastmatch_cog_registers_commands(lastmatch_cog):
    commands = [cmd.name for cmd in lastmatch_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
