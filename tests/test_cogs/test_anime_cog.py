import pytest
import discord
from unittest.mock import MagicMock, AsyncMock
from cogs.anime import AnimeCog

@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot

@pytest.fixture
def anime_cog(mock_bot):
    return AnimeCog(mock_bot)

def test_anime_cog_init(anime_cog):
    assert isinstance(anime_cog, AnimeCog)
    assert hasattr(anime_cog, "bot")

@pytest.mark.asyncio
async def test_anime_cog_registers_commands(anime_cog):
    commands = [cmd.name for cmd in anime_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
