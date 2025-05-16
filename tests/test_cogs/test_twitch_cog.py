import asyncio  # Добавляем импорт asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands  # Добавляем импорт app_commands

from cogs.twitch import TwitchCog


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    bot.loop = asyncio.get_event_loop()  # Для задач, запускаемых из __init__ или cog_load
    # Мокаем атрибут config
    bot.config = MagicMock()

    # Настраиваем mock для config.get, чтобы он возвращал разные значения для разных ключей
    def config_get_side_effect(key, default=None):
        if key == "TWITCH_CLIENT_ID":
            return "test_client_id"
        elif key == "TWITCH_CLIENT_SECRET":
            return "test_client_secret"
        return default

    bot.config.get = MagicMock(side_effect=config_get_side_effect)

    bot.tree = MagicMock(spec=app_commands.CommandTree)
    bot.add_cog = AsyncMock()
    return bot


@pytest.fixture
async def twitch_cog(mock_bot):
    cog = TwitchCog(mock_bot)
    # Мокаем зависимости, чтобы избежать внешних вызовов и реального запуска задач
    cog.twitch_api = AsyncMock()
    cog.twitch_api.initialize = AsyncMock()
    cog.twitch_api.close = AsyncMock()
    cog.data_manager = AsyncMock()
    cog.data_manager.initialize_table = AsyncMock()

    # Мокаем задачу и ее метод start
    cog.check_streams = MagicMock(
        spec=discord.ext.tasks.Loop
    )  # Используем spec для правильного мока
    cog.check_streams.start = MagicMock()
    cog.check_streams.cancel = MagicMock()
    cog.check_streams.is_running = MagicMock(return_value=False)

    # Вызываем cog_load, так как он содержит логику инициализации, включая запуск задач
    # Убедимся, что все необходимые моки на месте до вызова cog_load
    await cog.cog_load()
    return cog


@pytest.mark.asyncio
async def test_twitch_cog_init(twitch_cog):  # Тест должен быть async, так как фикстура async
    assert isinstance(twitch_cog, TwitchCog)
    assert hasattr(twitch_cog, "bot")


@pytest.mark.asyncio
async def test_twitch_cog_registers_commands(twitch_cog):
    # Проверяем app_commands через __cog_app_commands__
    app_cmds = twitch_cog.__cog_app_commands__
    assert isinstance(app_cmds, list)
    # В TwitchCog есть 3 app_commands: twitch_add, twitch_remove, twitch_list
    assert len(app_cmds) == 3
    command_names = sorted([cmd.name for cmd in app_cmds])
    assert command_names == sorted(["twitch_add", "twitch_remove", "twitch_list"])
