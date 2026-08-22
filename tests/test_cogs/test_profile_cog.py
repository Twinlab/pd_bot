"""Тесты команды единого профиля."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.activity import ActivityTracker
from cogs.profile import ProfileCog, setup
from utils.profile import ProfilePeriod, ProfileStats


@pytest.fixture
def profile_cog(mock_bot) -> ProfileCog:
    with patch("cogs.profile.ProfileStatsBuilder"):
        return ProfileCog(mock_bot)


@pytest.mark.asyncio
async def test_profile_command_opens_current_month(profile_cog, mock_context, mock_member) -> None:
    mock_context.author = mock_member
    profile_cog.send_from_context = AsyncMock()

    await profile_cog.profile.callback(profile_cog, mock_context)

    args = profile_cog.send_from_context.await_args.args
    assert args[0] is mock_context
    assert args[1] is mock_member
    assert args[2].scope == "month"


@pytest.mark.asyncio
async def test_profile_context_menu_is_ephemeral(profile_cog, mock_member) -> None:
    interaction = MagicMock(spec=discord.Interaction)
    profile_cog.send_from_interaction = AsyncMock()

    await profile_cog.profile_context_menu(interaction, mock_member)

    kwargs = profile_cog.send_from_interaction.await_args.kwargs
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("game", "cog_name"),
    [("dota", "LastMatchCog"), ("cs", "CsLastMatchCog")],
)
async def test_profile_match_button_sends_ephemeral_match(
    profile_cog, mock_bot, mock_member, game: str, cog_name: str
) -> None:
    sender = MagicMock()
    sender.send_last_match = AsyncMock()
    mock_bot.get_cog.return_value = sender
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await profile_cog._send_profile_match(interaction, mock_member, game)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    mock_bot.get_cog.assert_called_once_with(cog_name)
    sender.send_last_match.assert_awaited_once()
    context, target = sender.send_last_match.await_args.args
    assert context.bot is mock_bot
    assert context.author is interaction.user
    assert target is mock_member
    await context.send("готово", ephemeral=False)
    interaction.followup.send.assert_awaited_once_with(
        "готово",
        ephemeral=True,
        wait=True,
    )


@pytest.mark.asyncio
async def test_profile_match_button_handles_missing_cog(
    profile_cog, mock_bot, mock_member
) -> None:
    mock_bot.get_cog.return_value = None
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await profile_cog._send_profile_match(interaction, mock_member, "cs")

    mock_bot.get_cog.assert_called_once_with("CsLastMatchCog")
    interaction.followup.send.assert_awaited_once_with(
        "Просмотр матчей сейчас недоступен.",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_mystats_alias_delegates_to_profile(mock_bot, mock_context, mock_member) -> None:
    tracker = ActivityTracker.__new__(ActivityTracker)
    tracker.bot = mock_bot
    profile_cog = ProfileCog.__new__(ProfileCog)
    profile_cog.send_from_context = AsyncMock()
    mock_bot.get_cog.return_value = profile_cog
    mock_context.author = mock_member

    await tracker.mystats_command.callback(
        tracker,
        mock_context,
        month=6,
        year=2025,
    )

    period = profile_cog.send_from_context.await_args.args[2]
    assert period == ProfilePeriod("month", 2025, 6)


@pytest.mark.asyncio
async def test_mystatsall_alias_delegates_to_profile(mock_bot, mock_context, mock_member) -> None:
    tracker = ActivityTracker.__new__(ActivityTracker)
    tracker.bot = mock_bot
    profile_cog = ProfileCog.__new__(ProfileCog)
    profile_cog.send_from_context = AsyncMock()
    mock_bot.get_cog.return_value = profile_cog
    mock_context.author = mock_member

    await tracker.mystatsall_command.callback(tracker, mock_context)

    period = profile_cog.send_from_context.await_args.args[2]
    assert period == ProfilePeriod.all_time()


@pytest.mark.asyncio
async def test_setup_adds_profile_cog(mock_bot) -> None:
    mock_bot.add_cog = AsyncMock()

    with patch("cogs.profile.ProfileStatsBuilder"):
        await setup(mock_bot)

    added = mock_bot.add_cog.await_args.args[0]
    assert isinstance(added, commands.Cog)
