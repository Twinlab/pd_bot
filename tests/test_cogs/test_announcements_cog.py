"""Запуск анонсов только в production и только после готовности Discord."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.announcements import AnnouncementsCog, setup
from config.settings import ChannelConfig, Environment
from utils.release_announcements import ReleaseNote


@pytest.fixture
def cog(mock_bot, mock_text_channel):
    mock_bot.settings.environment = Environment.PRODUCTION
    mock_bot.settings.channels = ChannelConfig(announcements=mock_text_channel.id)
    mock_bot.settings.guild_id = mock_text_channel.guild.id
    mock_bot.get_channel.return_value = mock_text_channel
    instance = AnnouncementsCog(mock_bot)
    instance.announcer.publish = AsyncMock(return_value=True)
    with patch(
        "cogs.announcements.load_release_note",
        return_value=ReleaseNote(id="v1", text="Текст владельца"),
    ):
        yield instance


async def test_ready_reconnect_does_not_start_second_loop(cog):
    with (
        patch.object(cog.deliver_release, "is_running", side_effect=[False, True]),
        patch.object(cog.deliver_release, "start") as start,
    ):
        await cog.on_ready()
        await cog.on_ready()
    start.assert_called_once()


@pytest.mark.parametrize("environment", [Environment.DEVELOPMENT, Environment.TESTING])
async def test_non_production_never_sends(cog, environment):
    cog.bot.settings.environment = environment
    with patch.object(cog.deliver_release, "start") as start:
        await cog.on_ready()
    start.assert_not_called()


@pytest.mark.parametrize("published", [False, True])
async def test_delivery_finishes_loop_and_stays_finished_on_ready(cog, published):
    cog.announcer.publish.return_value = published
    with patch.object(cog.deliver_release, "stop") as stop:
        await cog.deliver_release.coro(cog)
    stop.assert_called_once()
    assert cog._completed
    args, kwargs = cog.announcer.publish.await_args
    assert args[0].text == "Текст владельца"
    assert args[1].id == cog.bot.settings.channels.announcements
    assert kwargs == {"bot_id": cog.bot.user.id}
    with patch.object(cog.deliver_release, "start") as start:
        await cog.on_ready()
    start.assert_not_called()


@pytest.mark.parametrize("missing", ["text", "channel"])
async def test_unconfigured_announcement_is_silent(cog, missing):
    if missing == "channel":
        cog.bot.settings.channels.announcements = None
    with patch(
        "cogs.announcements.load_release_note",
        return_value=ReleaseNote(id="v1", text="" if missing == "text" else "Обновление"),
    ):
        await cog.deliver_release.coro(cog)
    cog.announcer.publish.assert_not_awaited()
    assert cog._completed


async def test_error_is_logged_and_next_tick_can_deliver(cog):
    cog.announcer.publish.side_effect = RuntimeError("Временный сбой")
    with patch("cogs.announcements.logger") as logger:
        await cog.deliver_release.coro(cog)
    logger.exception.assert_called_once()
    assert not cog._completed
    cog.announcer.publish.side_effect = None
    await cog.deliver_release.coro(cog)
    assert cog._completed


@pytest.mark.parametrize("wrong", ["type", "guild"])
async def test_wrong_destination_cannot_receive_announcement(cog, wrong):
    if wrong == "type":
        cog.bot.get_channel.return_value = MagicMock(spec=discord.DMChannel)
    else:
        cog.bot.get_channel.return_value.guild = SimpleNamespace(id=999)
    await cog.deliver_release.coro(cog)
    cog.announcer.publish.assert_not_awaited()
    assert not cog._completed


async def test_missing_cached_channel_is_fetched(cog):
    channel = cog.bot.get_channel.return_value
    cog.bot.get_channel.return_value = None
    cog.bot.fetch_channel = AsyncMock(return_value=channel)
    await cog.deliver_release.coro(cog)
    cog.bot.fetch_channel.assert_awaited_once_with(channel.id)
    cog.announcer.publish.assert_awaited_once()


async def test_matching_guild_and_channel_ids_are_valid(cog):
    channel = cog.bot.get_channel.return_value
    cog.bot.settings.channels.announcements = channel.guild.id
    channel.id = channel.guild.id
    await cog.deliver_release.coro(cog)
    cog.announcer.publish.assert_awaited_once()
    assert cog._completed


async def test_unload_cancels_running_loop(cog):
    with (
        patch.object(cog.deliver_release, "is_running", return_value=True),
        patch.object(cog.deliver_release, "cancel") as cancel,
    ):
        await cog.cog_unload()
    cancel.assert_called_once()


async def test_setup_loads_announcements(mock_bot):
    mock_bot.add_cog = AsyncMock()
    await setup(mock_bot)
    assert isinstance(mock_bot.add_cog.await_args.args[0], AnnouncementsCog)


def test_announcement_channel_is_optional_for_existing_configs():
    assert ChannelConfig().announcements is None
