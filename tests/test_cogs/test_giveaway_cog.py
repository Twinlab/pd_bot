import pytest
import discord
from unittest.mock import MagicMock, AsyncMock
from cogs.giveaway import GiveawayCog

@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot

@pytest.fixture
def giveaway_cog(mock_bot):
    return GiveawayCog(mock_bot)

def test_giveaway_cog_init(giveaway_cog):
    assert isinstance(giveaway_cog, GiveawayCog)
    assert hasattr(giveaway_cog, "bot")

@pytest.mark.asyncio
async def test_giveaway_cog_registers_commands(giveaway_cog):
    commands = [cmd.name for cmd in giveaway_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
