"""Тесты команды единого профиля."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.profile import ProfileCog, setup


async def test_profile_registers_as_app_command_without_prefix():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    bot.settings = SimpleNamespace(steam_api_key=None, faceit_api_key=None)
    cog = ProfileCog(bot)
    await bot.add_cog(cog)
    assert bot.tree.get_command("profile") is not None
    assert bot.get_command("profile") is None
    assert bot.tree.get_command("profile").guild_only
    await bot.remove_cog("ProfileCog")


@pytest.fixture
def profile_cog(mock_bot) -> ProfileCog:
    with patch("cogs.profile.ProfileStatsBuilder"):
        return ProfileCog(mock_bot)


@pytest.mark.asyncio
async def test_profile_command_opens_current_month(
    profile_cog, mock_interaction, mock_member
) -> None:
    profile_cog.send_from_interaction = AsyncMock()

    await profile_cog.profile.callback(profile_cog, mock_interaction)

    args = profile_cog.send_from_interaction.await_args.args
    assert args[0] is mock_interaction
    assert args[1] is mock_member
    assert args[2].scope == "month"
    assert profile_cog.send_from_interaction.await_args.kwargs["ephemeral"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("ephemeral", [False, True])
async def test_profile_message_and_navigation_share_visibility(
    profile_cog, mock_interaction, mock_member, ephemeral
) -> None:
    from utils.profile import ProfilePeriod

    view = MagicMock()
    profile_cog.build_view = AsyncMock(return_value=view)
    period = ProfilePeriod.current_month()

    await profile_cog.send_from_interaction(
        mock_interaction, mock_member, period, ephemeral=ephemeral
    )

    mock_interaction.response.defer.assert_awaited_once_with(ephemeral=ephemeral)
    profile_cog.build_view.assert_awaited_once_with(
        target=mock_member,
        period=period,
        viewer_id=mock_interaction.user.id,
        public=not ephemeral,
    )
    mock_interaction.followup.send.assert_awaited_once_with(
        view=view, ephemeral=ephemeral, wait=True
    )
    assert view.message is mock_interaction.followup.send.return_value


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
async def test_profile_match_button_handles_missing_cog(profile_cog, mock_bot, mock_member) -> None:
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
async def test_setup_adds_profile_cog(mock_bot) -> None:
    mock_bot.add_cog = AsyncMock()

    with patch("cogs.profile.ProfileStatsBuilder"):
        await setup(mock_bot)

    added = mock_bot.add_cog.await_args.args[0]
    assert isinstance(added, commands.Cog)
