import pytest
import discord
from unittest.mock import MagicMock, AsyncMock
from cogs.fun import FunCog

@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot

@pytest.fixture
def fun_cog(mock_bot):
    return FunCog(mock_bot)

def test_fun_cog_init(fun_cog):
    assert isinstance(fun_cog, FunCog)
    assert hasattr(fun_cog, "bot")

@pytest.mark.asyncio
async def test_fun_cog_registers_commands(fun_cog):
    commands = [cmd.name for cmd in fun_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
