"""Тесты для кога TwitchCog."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from cogs.twitch import TwitchCog
from utils.twitch_api import TwitchAPI
from utils.twitch_data_manager import TwitchDataManager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def _collect_text(view: discord.ui.LayoutView) -> str:
    """Склеивает текст всех TextDisplay внутри LayoutView (с обходом контейнеров)."""
    texts: list[str] = []

    def walk(items) -> None:
        for item in items:
            if isinstance(item, discord.ui.TextDisplay):
                texts.append(item.content)
            children = getattr(item, "children", None)
            if children:
                walk(children)

    walk(view.children)
    return "\n".join(texts)


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.name = "Test Guild"
    guild.get_channel = MagicMock()
    guild.me = MagicMock(spec=discord.Member)
    return guild


@pytest.fixture
def mock_text_channel(mock_guild: discord.Guild):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 301
    channel.name = "twitch-notifications"
    channel.guild = mock_guild
    channel.permissions_for = MagicMock(
        return_value=MagicMock(send_messages=True, embed_links=True)
    )
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def mock_interaction(mock_guild: discord.Guild, mock_text_channel: discord.TextChannel):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = mock_guild
    interaction.guild_id = mock_guild.id
    interaction.channel = mock_text_channel
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup.send = AsyncMock()
    interaction.command = MagicMock(name="test_twitch_command")
    return interaction


@pytest.fixture
@patch("utils.twitch_data_manager.TwitchDataManager", spec=TwitchDataManager)
def mock_data_manager(MockDataManager):
    manager = MockDataManager.return_value
    manager.add_streamer = AsyncMock(return_value=True)
    manager.remove_streamer = AsyncMock(return_value=True)
    manager.get_streamers = AsyncMock(return_value=[])
    manager.update_twitch_id = AsyncMock()
    manager.update_streamer_status = AsyncMock()
    manager.update_notification_time = AsyncMock()
    return manager


@pytest.fixture
@patch("utils.twitch_api.TwitchAPI", spec=TwitchAPI)
def mock_twitch_api_class(MockTwitchAPI):
    api_instance = MockTwitchAPI.return_value
    api_instance.initialize = AsyncMock()
    api_instance.close = AsyncMock()
    api_instance.get_user_by_username = AsyncMock()
    api_instance.get_users = AsyncMock(return_value=[])
    api_instance.get_streams = AsyncMock(return_value=[])
    api_instance.is_user_live = AsyncMock(return_value=(False, None))
    return MockTwitchAPI


@pytest.fixture
def twitch_cog(
    mock_bot: commands.Bot, mock_data_manager: TwitchDataManager, mock_twitch_api_class: MagicMock
):
    mock_bot.guilds[0].id = 1
    with (
        patch("cogs.twitch.TwitchDataManager", return_value=mock_data_manager),
        patch("cogs.twitch.TwitchAPI", mock_twitch_api_class),
        patch("cogs.twitch.get_settings", return_value=mock_bot.settings),
    ):
        cog = TwitchCog(mock_bot)
        assert cog.data_manager is mock_data_manager
        if cog.twitch_api:
            assert cog.twitch_api is mock_twitch_api_class.return_value
        return cog


class TestTwitchCogInitAndLoad:
    def test_init_with_api_keys(self, mock_bot: commands.Bot):
        with (
            patch("cogs.twitch.TwitchDataManager"),
            patch("cogs.twitch.TwitchAPI") as MockTwitchAPIConstructor,
            patch("cogs.twitch.get_settings", return_value=mock_bot.settings),
        ):
            cog = TwitchCog(mock_bot)
            assert cog.client_id == "fake_twitch_id"
            assert cog.client_secret == "fake_twitch_secret"
            assert cog.twitch_api is not None
            MockTwitchAPIConstructor.assert_called_once_with("fake_twitch_id", "fake_twitch_secret")

    def test_init_without_api_keys(self, mock_bot: commands.Bot):
        mock_bot.settings.twitch_client_id = None
        mock_bot.settings.twitch_client_secret = None
        with (
            patch("cogs.twitch.TwitchDataManager"),
            patch("cogs.twitch.TwitchAPI") as MockTwitchAPIConstructor,
            patch("cogs.twitch.logger.warning") as mock_logger_warning,
            patch("cogs.twitch.get_settings", return_value=mock_bot.settings),
        ):
            cog = TwitchCog(mock_bot)
            assert cog.client_id == ""
            assert cog.client_secret == ""
            assert cog.twitch_api is None
            MockTwitchAPIConstructor.assert_not_called()
            mock_logger_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_cog_load_with_api(
        self, twitch_cog: TwitchCog, mock_data_manager: TwitchDataManager
    ):
        twitch_cog.twitch_api = AsyncMock(spec=TwitchAPI)
        twitch_cog.twitch_api.initialize = AsyncMock()

        with patch.object(twitch_cog.check_streams, "start") as mock_check_streams_start:
            await twitch_cog.cog_load()
            twitch_cog.twitch_api.initialize.assert_called_once()
            mock_check_streams_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_cog_load_without_api(
        self, mock_bot: commands.Bot, mock_data_manager: TwitchDataManager
    ):
        mock_bot.settings.twitch_client_id = None
        with (
            patch("cogs.twitch.TwitchDataManager", return_value=mock_data_manager),
            patch("cogs.twitch.TwitchAPI") as MockTwitchAPIConstructor,
            patch("cogs.twitch.logger.warning") as mock_logger_warning,
            patch("cogs.twitch.get_settings", return_value=mock_bot.settings),
        ):
            MockTwitchAPIConstructor.return_value = None

            cog = TwitchCog(mock_bot)
            cog.twitch_api = None

            with patch.object(cog.check_streams, "start") as mock_check_streams_start:
                await cog.cog_load()
                mock_check_streams_start.assert_not_called()
                assert any(
                    "Twitch API не инициализирован" in call_args[0][0]
                    for call_args in mock_logger_warning.call_args_list
                )


class TestTwitchCommands:
    @pytest.mark.asyncio
    async def test_twitch_add_success(
        self,
        twitch_cog: TwitchCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: TwitchDataManager,
        mock_text_channel: discord.TextChannel,
    ):
        twitch_username = "teststreamer"
        twitch_user_data = {"login": twitch_username, "id": "12345", "display_name": "TestStreamer"}

        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_user_by_username = AsyncMock(return_value=twitch_user_data)
        twitch_cog.twitch_api.is_user_live = AsyncMock(return_value=(False, None))

        await twitch_cog.twitch_add.callback(
            twitch_cog, mock_interaction, twitch_username=twitch_username, channel=mock_text_channel
        )

        twitch_cog.twitch_api.get_user_by_username.assert_called_once_with(twitch_username)
        mock_data_manager.add_streamer.assert_called_once_with(
            mock_interaction.guild_id, mock_text_channel.id, twitch_username, "12345"
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            f"Стример **{twitch_user_data['display_name']}** добавлен для отслеживания"
            in mock_interaction.response.send_message.call_args[0][0]
        )

    @pytest.mark.asyncio
    async def test_twitch_add_streamer_already_live(
        self,
        twitch_cog: TwitchCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: TwitchDataManager,
        mock_text_channel: discord.TextChannel,
        mock_guild: discord.Guild,
    ):
        twitch_username = "live_streamer"
        twitch_user_data = {"login": twitch_username, "id": "67890", "display_name": "LiveStreamer"}
        stream_data = {
            "id": "stream123",
            "title": "Live Stream Title",
            "user_name": "LiveStreamer",
            "game_name": "Cool Game",
            "viewer_count": 100,
            "thumbnail_url": "http://example.com/thumb-{width}x{height}.jpg",
        }

        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_user_by_username = AsyncMock(return_value=twitch_user_data)
        twitch_cog.twitch_api.is_user_live = AsyncMock(return_value=(True, stream_data))
        twitch_cog.send_stream_notification = AsyncMock(return_value=True)

        await twitch_cog.twitch_add.callback(
            twitch_cog, mock_interaction, twitch_username=twitch_username, channel=mock_text_channel
        )

        mock_data_manager.add_streamer.assert_called_once()
        mock_data_manager.update_streamer_status.assert_called_once_with(
            twitch_username, mock_interaction.guild_id, True, "stream123"
        )
        twitch_cog.send_stream_notification.assert_called_once_with(
            mock_interaction.guild_id, mock_text_channel.id, twitch_username, stream_data
        )
        mock_data_manager.update_notification_time.assert_called_once_with(
            twitch_username, mock_interaction.guild_id, "stream123"
        )
        mock_interaction.response.send_message.assert_called_once()
        assert "Стример сейчас в сети!" in mock_interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    async def test_twitch_add_live_stream_retries_failed_notification(
        self,
        twitch_cog: TwitchCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: TwitchDataManager,
        mock_text_channel: discord.TextChannel,
    ):
        """Неудачная доставка не помечает текущий стрим уже уведомлённым."""
        user = {"login": "live_streamer", "id": "67890", "display_name": "LiveStreamer"}
        stream_data = {
            "id": "stream123",
            "title": "Live Stream Title",
            "user_name": "LiveStreamer",
            "game_name": "Cool Game",
            "viewer_count": 100,
            "thumbnail_url": "http://example.com/thumb-{width}x{height}.jpg",
        }
        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_user_by_username = AsyncMock(return_value=user)
        twitch_cog.twitch_api.is_user_live = AsyncMock(return_value=(True, stream_data))
        twitch_cog.send_stream_notification = AsyncMock(return_value=False)

        await twitch_cog.twitch_add.callback(
            twitch_cog,
            mock_interaction,
            twitch_username=user["login"],
            channel=mock_text_channel,
        )

        mock_data_manager.update_streamer_status.assert_not_awaited()
        mock_data_manager.update_notification_time.assert_not_awaited()
        assert twitch_cog.streamers_cache[user["login"]]["is_live"] is False
        response = mock_interaction.response.send_message.call_args.args[0]
        assert "повторит попытку" in response

    @pytest.mark.asyncio
    async def test_twitch_add_user_not_found(
        self, twitch_cog: TwitchCog, mock_interaction: discord.Interaction
    ):
        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_user_by_username = AsyncMock(return_value=None)

        await twitch_cog.twitch_add.callback(
            twitch_cog, mock_interaction, twitch_username="nonexistent", channel=None
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            "Пользователь Twitch с именем **nonexistent** не найден."
            in mock_interaction.response.send_message.call_args.kwargs["embed"].description
        )

    @pytest.mark.asyncio
    async def test_twitch_add_no_api_keys(
        self, mock_bot: commands.Bot, mock_interaction: discord.Interaction
    ):
        mock_bot.settings.twitch_client_id = None
        with (
            patch("cogs.twitch.TwitchDataManager"),
            patch("cogs.twitch.TwitchAPI"),
            patch("cogs.twitch.get_settings", return_value=mock_bot.settings),
        ):
            cog_no_api = TwitchCog(mock_bot)
            await cog_no_api.twitch_add.callback(
                cog_no_api, mock_interaction, twitch_username="test", channel=None
            )
            mock_interaction.response.send_message.assert_called_once()
            assert (
                "Не указаны TWITCH_CLIENT_ID"
                in mock_interaction.response.send_message.call_args.kwargs["embed"].description
            )

    @pytest.mark.asyncio
    async def test_twitch_add_no_guild_id(
        self, twitch_cog: TwitchCog, mock_interaction: discord.Interaction
    ):
        mock_interaction.guild_id = None  # Имитируем отсутствие guild_id
        await twitch_cog.twitch_add.callback(
            twitch_cog, mock_interaction, twitch_username="test", channel=None
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            "Ошибка: не удалось определить ID сервера."
            in mock_interaction.response.send_message.call_args.kwargs["embed"].description
        )

    @pytest.mark.asyncio
    async def test_twitch_add_channel_not_text(
        self,
        twitch_cog: TwitchCog,
        mock_interaction: discord.Interaction,
        mock_guild: discord.Guild,
    ):
        # Имитируем, что команда вызвана не из текстового канала, и канал по умолчанию не найден
        mock_interaction.channel = MagicMock(spec=discord.VoiceChannel)  # Не текстовый канал
        mock_guild.get_channel.return_value = None  # Канал по умолчанию не найден
        twitch_cog.bot.get_guild.return_value = mock_guild  # Убедимся, что гильдия находится

        await twitch_cog.twitch_add.callback(
            twitch_cog, mock_interaction, twitch_username="test", channel=None
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            "Не удалось определить подходящий текстовый канал"
            in mock_interaction.response.send_message.call_args.kwargs["embed"].description
        )

    @pytest.mark.asyncio
    async def test_twitch_remove_success(
        self,
        twitch_cog: TwitchCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: TwitchDataManager,
    ):
        twitch_username = "teststreamer"
        mock_data_manager.remove_streamer.return_value = True
        await twitch_cog.twitch_remove.callback(
            twitch_cog, mock_interaction, twitch_username=twitch_username
        )
        mock_data_manager.remove_streamer.assert_called_once_with(
            mock_interaction.guild_id, twitch_username
        )
        assert twitch_username.lower() not in twitch_cog.streamers_cache
        mock_interaction.response.send_message.assert_called_once_with(
            f"Стример **{twitch_username}** удален из отслеживаемых.", ephemeral=True
        )

    @pytest.mark.asyncio
    async def test_twitch_remove_not_found(
        self,
        twitch_cog: TwitchCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: TwitchDataManager,
    ):
        twitch_username = "nonexistent"
        mock_data_manager.remove_streamer.return_value = False
        await twitch_cog.twitch_remove.callback(
            twitch_cog, mock_interaction, twitch_username=twitch_username
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            f"Стример **{twitch_username}** не найден в списке отслеживаемых."
            in mock_interaction.response.send_message.call_args.kwargs["embed"].description
        )

    @pytest.mark.asyncio
    async def test_twitch_list_empty(
        self,
        twitch_cog: TwitchCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: TwitchDataManager,
    ):
        mock_data_manager.get_streamers.return_value = []
        await twitch_cog.twitch_list.callback(twitch_cog, mock_interaction)
        mock_interaction.response.send_message.assert_called_once_with(
            "На этом сервере нет отслеживаемых Twitch-стримеров.", ephemeral=True
        )

    @pytest.mark.asyncio
    async def test_twitch_list_with_streamers(
        self,
        twitch_cog: TwitchCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: TwitchDataManager,
        mock_guild: discord.Guild,
    ):
        streamers_data = [
            {
                "twitch_username": "streamer1",
                "channel_id": 301,
                "is_live": True,
                "twitch_id": "s1id",
            },
            {
                "twitch_username": "streamer2",
                "channel_id": 301,
                "is_live": False,
                "twitch_id": "s2id",
            },
        ]
        mock_data_manager.get_streamers.return_value = streamers_data

        mock_text_channel_for_list = MagicMock(spec=discord.TextChannel, id=301, mention="<#301>")
        mock_guild.get_channel = MagicMock(return_value=mock_text_channel_for_list)
        mock_interaction.guild = mock_guild

        await twitch_cog.twitch_list.callback(twitch_cog, mock_interaction)
        mock_interaction.response.send_message.assert_called_once()
        args, kwargs = mock_interaction.response.send_message.call_args
        assert "embed" in kwargs
        embed = kwargs["embed"]
        assert embed.title == "Отслеживаемые Twitch-стримеры"
        assert len(embed.fields) == 1
        assert embed.fields[0].name == "Канал: <#301>"
        assert "[streamer1](https://twitch.tv/streamer1) - 🔴 В сети" in embed.fields[0].value
        assert "[streamer2](https://twitch.tv/streamer2) - ⚫ Не в сети" in embed.fields[0].value


class TestCheckStreamsTask:
    @pytest.mark.asyncio
    async def test_check_streams_no_streamers(
        self, twitch_cog: TwitchCog, mock_data_manager: TwitchDataManager
    ):
        mock_data_manager.get_streamers = AsyncMock(return_value=[])
        twitch_cog.first_run = False
        await twitch_cog.check_streams()
        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_users.assert_not_called()
        twitch_cog.twitch_api.get_streams.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_streams_new_stream_starts(
        self,
        twitch_cog: TwitchCog,
        mock_data_manager: TwitchDataManager,
        mock_guild: discord.Guild,
        mock_bot: commands.Bot,
    ):
        twitch_username = "newlylive"
        user_id = "user123"
        channel_id_for_notif = 777
        stream_id = "streamXYZ"

        streamers_db_data = [
            {
                "guild_id": mock_guild.id,
                "channel_id": channel_id_for_notif,
                "twitch_username": twitch_username,
                "twitch_id": user_id,
                "is_live": False,
                "last_stream_id": None,
                "last_notification_time": 0,
            }
        ]
        mock_data_manager.get_streamers = AsyncMock(return_value=streamers_db_data)

        twitch_user_api_data = [
            {"login": twitch_username, "id": user_id, "display_name": "NewlyLive"}
        ]
        twitch_streams_api_data = [
            {
                "user_id": user_id,
                "id": stream_id,
                "title": "Going Live!",
                "user_name": "NewlyLive",
                "game_name": "Game On",
                "viewer_count": 100,
                "thumbnail_url": "url-{width}x{height}",
            }
        ]

        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_users = AsyncMock(return_value=twitch_user_api_data)
        twitch_cog.twitch_api.get_streams = AsyncMock(return_value=twitch_streams_api_data)
        twitch_cog.send_stream_notification = AsyncMock(return_value=True)

        mock_bot.guilds = [mock_guild]
        twitch_cog.bot = mock_bot

        twitch_cog.first_run = False
        await twitch_cog.check_streams()

        twitch_cog.twitch_api.get_users.assert_called_once_with([twitch_username])
        twitch_cog.twitch_api.get_streams.assert_called_once_with([user_id])
        mock_data_manager.update_streamer_status.assert_called_once_with(
            twitch_username, mock_guild.id, True, stream_id
        )
        twitch_cog.send_stream_notification.assert_called_once_with(
            mock_guild.id, channel_id_for_notif, twitch_username, twitch_streams_api_data[0]
        )
        mock_data_manager.update_notification_time.assert_called_once_with(
            twitch_username, mock_guild.id, stream_id
        )
        assert twitch_cog.streamers_cache[twitch_username]["is_live"] is True

    @pytest.mark.asyncio
    async def test_check_streams_restart_does_not_repeat_known_stream(
        self,
        twitch_cog: TwitchCog,
        mock_data_manager: TwitchDataManager,
    ):
        """Состояние первого poll восстанавливается из БД после рестарта."""
        username = "alreadylive"
        user_id = "user123"
        stream_id = "streamXYZ"
        mock_data_manager.get_streamers = AsyncMock(
            return_value=[
                {
                    "guild_id": 1,
                    "channel_id": 777,
                    "twitch_username": username,
                    "twitch_id": user_id,
                    "is_live": True,
                    "last_stream_id": stream_id,
                    "last_notification_time": 1000,
                }
            ]
        )
        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_users = AsyncMock(
            return_value=[{"login": username, "id": user_id}]
        )
        twitch_cog.twitch_api.get_streams = AsyncMock(
            return_value=[
                {
                    "user_id": user_id,
                    "id": stream_id,
                    "title": "Still live",
                    "user_name": "AlreadyLive",
                    "game_name": "Game",
                    "viewer_count": 10,
                    "thumbnail_url": "url-{width}x{height}",
                }
            ]
        )
        twitch_cog.send_stream_notification = AsyncMock(return_value=True)
        twitch_cog.first_run = False

        await twitch_cog.check_streams()

        twitch_cog.send_stream_notification.assert_not_awaited()
        mock_data_manager.update_streamer_status.assert_not_awaited()
        assert twitch_cog.streamers_cache[username]["is_live"] is True
        assert twitch_cog.streamers_cache[username]["last_stream_id"] == stream_id

    @pytest.mark.asyncio
    async def test_check_streams_retries_when_notification_failed(
        self,
        twitch_cog: TwitchCog,
        mock_data_manager: TwitchDataManager,
    ):
        """Не фиксирует live-переход, пока Discord не принял уведомление."""
        username = "newlylive"
        user_id = "user123"
        stream_id = "streamXYZ"
        mock_data_manager.get_streamers = AsyncMock(
            return_value=[
                {
                    "guild_id": 1,
                    "channel_id": 777,
                    "twitch_username": username,
                    "twitch_id": user_id,
                    "is_live": False,
                    "last_stream_id": None,
                    "last_notification_time": 0,
                }
            ]
        )
        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_users = AsyncMock(
            return_value=[{"login": username, "id": user_id}]
        )
        twitch_cog.twitch_api.get_streams = AsyncMock(
            return_value=[
                {
                    "user_id": user_id,
                    "id": stream_id,
                    "title": "New live",
                    "user_name": "NewlyLive",
                    "game_name": "Game",
                    "viewer_count": 10,
                    "thumbnail_url": "url-{width}x{height}",
                }
            ]
        )
        twitch_cog.send_stream_notification = AsyncMock(return_value=False)
        twitch_cog.first_run = False

        await twitch_cog.check_streams()

        mock_data_manager.update_streamer_status.assert_not_awaited()
        mock_data_manager.update_notification_time.assert_not_awaited()
        assert twitch_cog.streamers_cache[username]["is_live"] is False

    @pytest.mark.asyncio
    async def test_check_streams_repairs_status_without_duplicate_notification(
        self,
        twitch_cog: TwitchCog,
        mock_data_manager: TwitchDataManager,
    ):
        """Известный stream ID считается уже отправленным даже при stale is_live."""
        username = "knownstream"
        user_id = "user123"
        stream_id = "streamXYZ"
        mock_data_manager.get_streamers = AsyncMock(
            return_value=[
                {
                    "guild_id": 1,
                    "channel_id": 777,
                    "twitch_username": username,
                    "twitch_id": user_id,
                    "is_live": False,
                    "last_stream_id": stream_id,
                    "last_notification_time": 1000,
                }
            ]
        )
        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_users = AsyncMock(
            return_value=[{"login": username, "id": user_id}]
        )
        twitch_cog.twitch_api.get_streams = AsyncMock(
            return_value=[
                {
                    "user_id": user_id,
                    "id": stream_id,
                    "title": "Known live",
                    "user_name": "KnownStream",
                    "game_name": "Game",
                    "viewer_count": 10,
                    "thumbnail_url": "url-{width}x{height}",
                }
            ]
        )
        twitch_cog.send_stream_notification = AsyncMock(return_value=True)
        twitch_cog.first_run = False

        await twitch_cog.check_streams()

        twitch_cog.send_stream_notification.assert_not_awaited()
        mock_data_manager.update_streamer_status.assert_awaited_once_with(
            username,
            1,
            True,
            stream_id,
        )
        assert twitch_cog.streamers_cache[username]["is_live"] is True

    @pytest.mark.asyncio
    async def test_check_streams_stream_ends(
        self,
        twitch_cog: TwitchCog,
        mock_data_manager: TwitchDataManager,
        mock_guild: discord.Guild,
        mock_bot: commands.Bot,
    ):
        twitch_username = "goingoffline"
        user_id = "user456"

        twitch_cog.streamers_cache[twitch_username] = {
            "user_id": user_id,
            "is_live": True,
            "stream_data": {"id": "oldStream"},
        }
        streamers_db_data = [
            {
                "guild_id": mock_guild.id,
                "channel_id": 777,
                "twitch_username": twitch_username,
                "twitch_id": user_id,
                "is_live": True,
                "last_stream_id": "oldStream",
                "last_notification_time": 1000,
            }
        ]
        mock_data_manager.get_streamers = AsyncMock(return_value=streamers_db_data)

        twitch_user_api_data = [
            {"login": twitch_username, "id": user_id, "display_name": "GoingOffline"}
        ]
        twitch_streams_api_data = []

        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_users = AsyncMock(return_value=twitch_user_api_data)
        twitch_cog.twitch_api.get_streams = AsyncMock(return_value=twitch_streams_api_data)
        twitch_cog.send_stream_notification = AsyncMock()

        mock_bot.guilds = [mock_guild]
        twitch_cog.bot = mock_bot

        twitch_cog.first_run = False
        await twitch_cog.check_streams()

        mock_data_manager.update_streamer_status.assert_called_once_with(
            twitch_username, mock_guild.id, False
        )
        twitch_cog.send_stream_notification.assert_not_called()
        assert twitch_cog.streamers_cache[twitch_username]["is_live"] is False

    @pytest.mark.asyncio
    async def test_check_streams_update_twitch_id_if_missing(
        self,
        twitch_cog: TwitchCog,
        mock_data_manager: TwitchDataManager,
        mock_guild: discord.Guild,
        mock_bot: commands.Bot,
    ):
        twitch_username = "needsid"
        user_id_from_api = "newly_fetched_id"
        streamers_db_data = [
            {
                "guild_id": mock_guild.id,
                "channel_id": 777,
                "twitch_username": twitch_username,
                "twitch_id": None,
                "is_live": False,
                "last_stream_id": None,
                "last_notification_time": 0,
            }
        ]  # twitch_id is None
        mock_data_manager.get_streamers = AsyncMock(return_value=streamers_db_data)

        twitch_user_api_data = [
            {"login": twitch_username, "id": user_id_from_api, "display_name": "NeedsID"}
        ]
        twitch_streams_api_data = []  # Not live

        assert twitch_cog.twitch_api is not None
        twitch_cog.twitch_api.get_users = AsyncMock(return_value=twitch_user_api_data)
        twitch_cog.twitch_api.get_streams = AsyncMock(return_value=twitch_streams_api_data)

        mock_bot.guilds = [mock_guild]
        twitch_cog.bot = mock_bot
        twitch_cog.first_run = False

        await twitch_cog.check_streams()

        mock_data_manager.update_twitch_id.assert_called_once_with(
            twitch_username, mock_guild.id, user_id_from_api
        )


class TestSendStreamNotification:
    @pytest.mark.asyncio
    async def test_send_notification_success(
        self,
        twitch_cog: TwitchCog,
        mock_bot: commands.Bot,
        mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel,
    ):
        username = "teststreamer"
        stream_data = {
            "title": "Test Stream",
            "user_name": "TestStreamer",
            "game_name": "Test Game",
            "viewer_count": 10,
            "thumbnail_url": "http://example.com/{width}x{height}.jpg",
        }

        mock_bot.get_guild = MagicMock(
            return_value=mock_guild
        )  # bot.get_guild(guild_id) → mock_guild
        mock_guild.get_channel.return_value = mock_text_channel  # get_channel находит наш канал

        result = await twitch_cog.send_stream_notification(
            mock_guild.id, mock_text_channel.id, username, stream_data
        )
        assert result is True
        mock_text_channel.send.assert_called_once()
        args, kwargs = mock_text_channel.send.call_args
        assert "embed" not in kwargs
        view = kwargs["view"]
        text = _collect_text(view)
        assert "Test Stream" in text
        assert "TestStreamer" in text
        assert "Test Game" in text

    @pytest.mark.asyncio
    async def test_send_notification_empty_stream_data(
        self, twitch_cog: TwitchCog, mock_bot: commands.Bot
    ):
        """Проверяет, что пустой stream_data вызывает ранний возврат."""
        with patch("cogs.twitch.logger.error") as mock_logger_error:
            result = await twitch_cog.send_stream_notification(1, 301, "test", {})
            assert result is False
            mock_logger_error.assert_called_once()
            assert "Неполные данные стрима" in mock_logger_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_send_notification_bot_not_ready(
        self, twitch_cog: TwitchCog, mock_bot: commands.Bot
    ):
        mock_bot.is_ready = MagicMock(return_value=False)
        stream_data = {
            "title": "T",
            "user_name": "U",
            "thumbnail_url": "http://x/{width}x{height}",
            "game_name": "G",
            "viewer_count": 0,
        }
        with patch("cogs.twitch.logger.error") as mock_logger_error:
            await twitch_cog.send_stream_notification(1, 301, "test", stream_data)
            mock_logger_error.assert_called_once_with(
                "Бот не готов при попытке отправить уведомление о стриме test"
            )

    @pytest.mark.asyncio
    async def test_send_notification_guild_not_cached(
        self, twitch_cog: TwitchCog, mock_bot: commands.Bot
    ):
        mock_bot.get_guild = MagicMock(return_value=None)
        stream_data = {
            "title": "T",
            "user_name": "U",
            "thumbnail_url": "http://x/{width}x{height}",
            "game_name": "G",
            "viewer_count": 0,
        }
        with patch("cogs.twitch.logger.error") as mock_logger_error:
            await twitch_cog.send_stream_notification(1, 301, "test", stream_data)
            mock_logger_error.assert_called_once_with(
                "Гильдия с ID %s не найдена в кеше Discord", 1
            )

    @pytest.mark.asyncio
    async def test_send_notification_channel_not_found_uses_default(
        self,
        twitch_cog: TwitchCog,
        mock_bot: commands.Bot,
        mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel,
    ):
        username = "teststreamer"
        stream_data = {
            "title": "Test Stream",
            "user_name": "TestStreamer",
            "game_name": "Test Game",
            "viewer_count": 10,
            "thumbnail_url": "http://example.com/{width}x{height}.jpg",
        }

        mock_bot.get_guild = MagicMock(return_value=mock_guild)
        # Первый get_channel (для channel_id) вернет None
        # Второй get_channel (для default_channel_id) вернет mock_text_channel
        mock_guild.get_channel.side_effect = [None, mock_text_channel]

        await twitch_cog.send_stream_notification(
            mock_guild.id, 999, username, stream_data
        )  # 999 - несуществующий ID
        mock_text_channel.send.assert_called_once()  # Должен отправить в default канал
        assert mock_guild.get_channel.call_count == 2

    @pytest.mark.asyncio
    async def test_send_notification_no_embed_permission(
        self,
        twitch_cog: TwitchCog,
        mock_bot: commands.Bot,
        mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel,
    ):
        username = "teststreamer"
        stream_data = {
            "title": "Test Stream",
            "user_name": "TestStreamer",
            "game_name": "Test Game",
            "viewer_count": 10,
            "thumbnail_url": "http://example.com/{width}x{height}.jpg",
        }
        mock_bot.get_guild = MagicMock(return_value=mock_guild)
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.permissions_for.return_value = MagicMock(
            send_messages=True, embed_links=False
        )  # Нет прав на эмбеды

        await twitch_cog.send_stream_notification(
            mock_guild.id, mock_text_channel.id, username, stream_data
        )
        mock_text_channel.send.assert_called_once()
        args, kwargs = mock_text_channel.send.call_args
        assert "embed" not in kwargs  # Не должно быть эмбеда
        assert "content" in kwargs
        assert (
            "https://twitch.tv/teststreamer" in kwargs["content"]
        )  # Проверяем наличие ссылки в текстовом сообщении


class TestCogCommandErrorHandling:
    @pytest.mark.asyncio
    async def test_cog_command_error_delegates_to_global_handler(
        self, twitch_cog: TwitchCog, mock_interaction: discord.Interaction
    ):
        """Ког делегирует ошибки единому handle_app_command_error (унифицированный embed)."""
        error = app_commands.CommandInvokeError(MagicMock(), ValueError("Original error detail"))

        # Случай, когда interaction.response.is_done() == False — отвечаем напрямую.
        mock_interaction.response.is_done = MagicMock(return_value=False)
        await twitch_cog.cog_app_command_error(mock_interaction, error)
        mock_interaction.response.send_message.assert_called_once()
        embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
        assert embed.title == "❌ Ошибка"
        assert "Original error detail" in embed.description

        # Случай, когда interaction.response.is_done() == True — через followup.
        mock_interaction.response.send_message.reset_mock()
        mock_interaction.response.is_done = MagicMock(return_value=True)
        await twitch_cog.cog_app_command_error(mock_interaction, error)
        mock_interaction.followup.send.assert_called_once()
        assert mock_interaction.followup.send.call_args.kwargs["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_cog_command_error_send_fails(
        self, twitch_cog: TwitchCog, mock_interaction: discord.Interaction
    ):
        """Если отправка падает с HTTPException — ошибка логируется, не пробрасывается."""
        error = app_commands.CommandInvokeError(MagicMock(), Exception("Test error"))
        mock_interaction.response.is_done = MagicMock(return_value=False)
        mock_interaction.response.send_message.side_effect = discord.HTTPException(
            MagicMock(), "Failed to send error"
        )

        with patch("utils.error_handler.logger.error") as mock_logger_error:
            await twitch_cog.cog_app_command_error(mock_interaction, error)
            assert any(
                "Не удалось отправить сообщение об ошибке slash-команды" in call_args[0][0]
                for call_args in mock_logger_error.call_args_list
            )


@pytest.mark.asyncio
async def test_setup_function(mock_bot: commands.Bot):
    from cogs.twitch import setup as setup_cog

    mock_bot.add_cog = AsyncMock()
    with patch("cogs.twitch.logger.info") as mock_logger_info:
        await setup_cog(mock_bot)
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], TwitchCog)
        mock_logger_info.assert_called_once_with("Ког TwitchCog успешно загружен.")
