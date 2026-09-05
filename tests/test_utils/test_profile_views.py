"""Тесты Components V2-представления профиля."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils.profile import (
    FaceitAccount,
    ProfileAccounts,
    ProfileMoment,
    ProfilePeriod,
    ProfileStats,
    ProfileStatsBuilder,
    ProfileView,
)


def _member() -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.display_name = "@everyone **Twin**"
    member.activities = []
    member.joined_at = datetime(2024, 1, 15, tzinfo=UTC)
    member.display_avatar = MagicMock()
    member.display_avatar.url = "https://cdn.example/avatar.png"
    return member


def _view(*, match_callback: AsyncMock | None = None) -> ProfileView:
    stats = ProfileStats(
        period=ProfilePeriod("month", 2026, 7),
        messages=1234,
        voice_seconds=7200,
        reactions=42,
        top_games=[("@everyone **Dota 2**", 3600), ("Counter-Strike 2", 1800)],
        message_rank=2,
        voice_rank=1,
        reaction_rank=3,
        current_game="@here Test Game",
    )
    return ProfileView(
        target=_member(),
        builder=MagicMock(spec=ProfileStatsBuilder),
        stats=stats,
        eligible_user_ids={1},
        match_callback=match_callback,
    )


@pytest.mark.asyncio
async def test_moments_recheck_channel_permissions_after_previous_visit() -> None:
    view = _view()
    guild = MagicMock(spec=discord.Guild)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 20
    channel.overwrites = {}
    channel.permissions_for.return_value = discord.Permissions(
        view_channel=True, read_message_history=True
    )
    guild.channels = [channel]
    guild.threads = []
    view.target.guild = guild
    moment = ProfileMoment("Публичный момент", "https://discord.com/channels/1/20/30", 7)

    async def build_moments(**kwargs):
        return [moment] if 20 in kwargs["allowed_channel_ids"] else []

    view.builder.build_moments = AsyncMock(side_effect=build_moments)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.defer = AsyncMock()
    interaction.edit_original_response = AsyncMock()

    await view.show_tab(interaction, "moments")
    assert "Публичный момент" in str(view.to_components())

    channel.permissions_for.return_value.view_channel = False
    await view.show_tab(interaction, "moments")

    assert "Публичный момент" not in str(view.to_components())
    assert view.builder.build_moments.await_count == 2
    assert view.builder.build_moments.await_args.kwargs["allowed_channel_ids"] == set()


def test_profile_view_serializes_without_wrapped_or_unsafe_mentions() -> None:
    """Начальная карточка остаётся в лимите и не раскрывает wrapped."""
    view = _view()

    payload = str(view.to_components())

    assert view.total_children_count <= 40
    assert "Wrapped" not in payload
    assert "wrapped" not in payload
    assert "@everyone" not in payload
    assert "@here" not in payload
    assert "Обзор" in payload
    assert "Игры" in payload
    assert "Моменты" in payload
    assert "Аккаунты" in payload


def test_each_tab_stays_in_component_limit_without_duplicate_summary() -> None:
    view = _view()
    view._moments_cache[view.period] = [
        ProfileMoment("Первый", "https://discord.com/channels/1/2/3", 9),
        ProfileMoment("Второй", "https://discord.com/channels/1/2/4", 5),
        ProfileMoment("Третий", "https://discord.com/channels/1/2/5", 3),
    ]
    view._accounts = ProfileAccounts(
        dota_ids=(12345,),
        faceit=(FaceitAccount("faceit-id", "Player One"),),
    )

    for tab in ("overview", "games", "moments", "accounts"):
        view.active_tab = tab  # type: ignore[assignment]
        view._render()
        payload = str(view.to_components())
        assert view.total_children_count <= 40
        if tab == "moments":
            assert "Сообщения:" not in payload
            assert "В голосе:" not in payload
        if tab == "accounts":
            assert "Этот месяц" not in payload
            assert "Всё время" not in payload


@pytest.mark.asyncio
async def test_any_member_can_switch_profile_tabs() -> None:
    view = _view()
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = 2

    allowed = await view.interaction_check(interaction)

    assert allowed is True


@pytest.mark.asyncio
async def test_last_match_action_uses_profile_target() -> None:
    callback = AsyncMock()
    view = _view(match_callback=callback)
    interaction = MagicMock(spec=discord.Interaction)

    await view.show_last_match(interaction, "dota")

    callback.assert_awaited_once_with(interaction, view.target, "dota")


@pytest.mark.asyncio
async def test_repeated_match_action_is_rejected_for_same_user() -> None:
    callback = AsyncMock()
    view = _view(match_callback=callback)
    view._active_match_requests.add(2)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(id=2)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await view.show_last_match(interaction, "dota")

    callback.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once_with(
        "Последний матч уже загружается.",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_match_action_releases_user_after_error() -> None:
    callback = AsyncMock(side_effect=RuntimeError("boom"))
    view = _view(match_callback=callback)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(id=2)

    with pytest.raises(RuntimeError, match="boom"):
        await view.show_last_match(interaction, "cs")

    assert view._active_match_requests == set()


def test_last_match_buttons_are_rendered_when_callback_is_available() -> None:
    view = _view(match_callback=AsyncMock())

    payload = str(view.to_components())

    assert "Последний матч Dota 2" in payload
    assert "Последний матч CS2" in payload
    assert view.total_children_count <= 40


@pytest.mark.asyncio
async def test_component_error_returns_same_incident_id_as_log() -> None:
    view = _view(match_callback=AsyncMock())
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(id=2)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    error = RuntimeError("private detail")
    item = MagicMock(spec=discord.ui.Item)

    with (
        patch("utils.profile.views.new_incident_id", return_value="FACE01"),
        patch("utils.profile.views.logger") as mock_logger,
    ):
        await view.on_error(interaction, error, item)

    message = interaction.response.send_message.await_args.args[0]
    assert "FACE01" in message
    assert "private detail" not in message
    assert mock_logger.error.call_args.kwargs["extra"]["context"]["incident_id"] == "FACE01"
