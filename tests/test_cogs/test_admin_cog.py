import pytest
import discord
from unittest.mock import MagicMock, AsyncMock
from cogs.admin import AdminCog

@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot

@pytest.fixture
def admin_cog(mock_bot):
    return AdminCog(mock_bot)

def test_admin_cog_init(admin_cog):
    assert isinstance(admin_cog, AdminCog)
    assert hasattr(admin_cog, "bot")

@pytest.mark.asyncio
async def test_admin_cog_registers_commands(admin_cog):
    # Проверяем, что команды cog зарегистрированы
    commands = [cmd.name for cmd in admin_cog.get_commands()]
    assert isinstance(commands, list)
    # Smoke: хотя бы одна команда есть
    assert len(commands) > 0
