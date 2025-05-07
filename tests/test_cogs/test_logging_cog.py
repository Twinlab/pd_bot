import pytest
import discord
from unittest.mock import MagicMock, AsyncMock
from cogs.logging_cog import LoggingCog

@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    # Мокаем атрибут config
    bot.config = MagicMock()
    # Мокаем метод get на объекте config
    # Возвращаем какое-то значение по умолчанию, чтобы тест инициализации проходил
    # Для LoggingCog, get может вызываться с двумя аргументами (ключ и значение по умолчанию)
    bot.config.get = MagicMock(return_value=1365045098785542224) # Пример ID канала
    return bot

@pytest.fixture
def logging_cog(mock_bot):
    return LoggingCog(mock_bot)

def test_logging_cog_init(logging_cog):
    assert isinstance(logging_cog, LoggingCog)
    assert hasattr(logging_cog, "bot")

