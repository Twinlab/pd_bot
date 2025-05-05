import pytest
import discord
from unittest.mock import MagicMock, AsyncMock
from cogs.twitch import TwitchCog

@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot

@pytest.fixture
def twitch_cog(mock_bot):
    return TwitchCog(mock_bot)

def test_twitch_cog_init(twitch_cog):
    assert isinstance(twitch_cog, TwitchCog)
    assert hasattr(twitch_cog, "bot")

@pytest.mark.asyncio
async def test_twitch_cog_registers_commands(twitch_cog):
    commands = [cmd.name for cmd in twitch_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
