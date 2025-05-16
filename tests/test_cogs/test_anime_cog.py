from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.anime import AnimeCog


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    # Мокаем атрибут config
    bot.config = MagicMock()
    # Мокаем метод get на объекте config
    # Возвращаем какое-то значение по умолчанию, чтобы тест инициализации проходил
    bot.config.get = MagicMock(return_value=123456789012345678)  # Пример ID канала
    return bot


@pytest.fixture
async def anime_cog(mock_bot):
    cog = AnimeCog(mock_bot)
    # Мокаем метод start у задачи, чтобы она не запускалась в тестах
    cog.morning_post.start = AsyncMock()
    return cog


@pytest.mark.asyncio
async def test_anime_cog_init(anime_cog):
    assert isinstance(anime_cog, AnimeCog)
    assert hasattr(anime_cog, "bot")


@pytest.mark.asyncio
async def test_anime_cog_registers_commands(anime_cog):
    commands = [cmd.name for cmd in anime_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
