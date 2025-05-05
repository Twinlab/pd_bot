import pytest
import discord
from unittest.mock import MagicMock, AsyncMock
from cogs.logging_cog import LoggingCog

@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot

@pytest.fixture
def logging_cog(mock_bot):
    return LoggingCog(mock_bot)

def test_logging_cog_init(logging_cog):
    assert isinstance(logging_cog, LoggingCog)
    assert hasattr(logging_cog, "bot")

@pytest.mark.asyncio
async def test_logging_cog_registers_commands(logging_cog):
    commands = [cmd.name for cmd in logging_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
