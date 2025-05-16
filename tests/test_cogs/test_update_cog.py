from unittest.mock import MagicMock

import discord
import pytest

from cogs.update import UpdateCog


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot


@pytest.fixture
def update_cog(mock_bot):
    return UpdateCog(mock_bot)


def test_update_cog_init(update_cog):
    assert isinstance(update_cog, UpdateCog)
    assert hasattr(update_cog, "bot")


@pytest.mark.asyncio
async def test_update_cog_registers_commands(update_cog):
    commands = [cmd.name for cmd in update_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
