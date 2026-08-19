"""Конфигурационный файл для pytest, содержит общие фикстуры и хуки."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

# Добавляем корень проекта в sys.path для корректного импорта модулей
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


# Импортируем BotSettings для мока
from config.settings import BotSettings


@pytest.fixture
def mock_bot():
    """Создает мок бота Discord с моком настроек."""
    bot = MagicMock(spec=commands.Bot)
    bot.user = MagicMock(spec=discord.User)
    bot.user.id = 123456789
    bot.user.name = "Test Bot"
    bot.user.display_name = "Test Bot"

    # Создаем полностью мокнутый объект настроек, чтобы избежать чтения файла
    settings = MagicMock(spec=BotSettings)
    settings.bot_token = "fake_token"
    settings.stratz_api_key = "fake_api_key"
    settings.prefix = "!"
    settings.channels = MagicMock()
    settings.channels.activity_reports = 573665353327181824
    settings.channels.anime = 298811309640646666
    settings.channels.logging = 1365045098785542224 # Добавим ID для логгирования
    settings.twitch_client_id = "fake_twitch_id"
    settings.twitch_client_secret = "fake_twitch_secret"
    settings.limits = MagicMock()
    settings.limits.logging_buffer_overhead = 10
    settings.limits.max_message_length = 1990
    settings.timeouts = MagicMock()
    settings.timeouts.log_check_interval = 5

    settings.messages = MagicMock()
    settings.messages.errors = {
        "twitch_api_not_configured": "Не указаны TWITCH_CLIENT_ID и/или TWITCH_CLIENT_SECRET в конфиге. Функционал Twitch будет отключен."
    }

    settings.twitch = MagicMock()
    settings.twitch.check_interval = 60
    settings.twitch.notification_timeout = 3600
    settings.twitch.startup_delay = 1
    settings.twitch.embed_color = "#9146FF"
    settings.limits.twitch_streamers_chunk = 900

    settings.update = MagicMock()
    settings.update.restart_command = "systemctl --user restart discord-bot.service"
    settings.timeouts.update_restart_delay = 3
    settings.limits.update_output_max_length = 1900

    bot.settings = settings

    # По умолчанию бот на одном сервере, где все пользователи "найдены"
    # (нужно для stale session cleanup в update_current_activities)
    default_guild = MagicMock(spec=discord.Guild)
    default_guild.id = 111222333
    default_guild.get_member = MagicMock(return_value=MagicMock())
    bot.guilds = [default_guild]

    return bot


@pytest.fixture
def mock_guild():
    """Создает мок гильдии Discord."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 111222333
    guild.name = "Test Guild"
    guild.me = MagicMock(spec=discord.Member)
    guild.me.id = 123456789
    guild.me.name = "Test Bot"
    guild.me.display_name = "Test Bot"
    return guild


@pytest.fixture
def mock_member(mock_guild):
    """Создает мок участника Discord."""
    member = MagicMock(spec=discord.Member)
    member.id = 987654321
    member.name = "Test User"
    member.display_name = "Test User"
    member.mention = "<@987654321>"
    member.guild = mock_guild
    return member


@pytest.fixture
def mock_text_channel(mock_guild):
    """Создает мок текстового канала Discord."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 444555666
    channel.name = "test-channel"
    channel.guild = mock_guild
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def mock_voice_channel(mock_guild):
    """Создает мок голосового канала Discord."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 777888999
    channel.name = "test-voice-channel"
    channel.guild = mock_guild
    channel.members = []
    return channel


@pytest.fixture
def mock_message(mock_member, mock_text_channel):
    """Создает мок сообщения Discord."""
    message = MagicMock(spec=discord.Message)
    message.id = 123123123
    message.content = "!test"
    message.author = mock_member
    message.guild = mock_member.guild
    message.channel = mock_text_channel
    return message


@pytest.fixture
def mock_context(mock_bot, mock_message):
    """Создает мок контекста команды Discord."""
    ctx = MagicMock(spec=commands.Context)
    ctx.bot = mock_bot
    ctx.author = mock_message.author
    ctx.guild = mock_message.guild
    ctx.channel = mock_message.channel
    ctx.message = mock_message
    ctx.send = AsyncMock()
    return ctx


@pytest.fixture
def mock_interaction(mock_bot, mock_member, mock_text_channel):
    """Создает мок взаимодействия Discord."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.bot = mock_bot
    interaction.user = mock_member
    interaction.guild_id = mock_member.guild.id
    interaction.guild = mock_member.guild
    interaction.channel_id = mock_text_channel.id
    interaction.channel = mock_text_channel
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


@pytest.fixture
def mock_voice_client(mock_bot, mock_voice_channel):
    """Создает мок голосового клиента Discord."""
    voice_client = MagicMock(spec=discord.VoiceClient)
    voice_client.is_connected = MagicMock(return_value=True)
    voice_client.is_playing = MagicMock(return_value=False)
    voice_client.is_paused = MagicMock(return_value=False)
    voice_client.play = MagicMock()
    voice_client.pause = MagicMock()
    voice_client.resume = MagicMock()
    voice_client.stop = MagicMock()
    voice_client.disconnect = AsyncMock()
    voice_client.move_to = AsyncMock()
    voice_client.channel = mock_voice_channel
    return voice_client


@pytest.fixture
def mock_db():
    """Создает мок базы данных."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.fetchall = AsyncMock(return_value=[])
    db.fetchone = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    return db
