"""Тесты Components V2-представления профиля."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils.profile import (
    ProfileMoment,
    ProfilePeriod,
    ProfileStats,
    ProfileStatsBuilder,
    ProfileView,
)
from utils.profile.account_views import (
    AccountConfirmView,
    AccountLinkModal,
    AccountRemoveView,
    account_choices,
)
from utils.profile.accounts import ProfileAccountService, ResolvedAccount
from utils.profile.builder import FaceitAccount, ProfileAccounts
from utils.profile_accounts_data_manager import AccountLinkError


def _account_view(*, viewer_id=1, accounts=None):
    view = _view(match_callback=AsyncMock())
    view.viewer_id = viewer_id
    view.account_service = MagicMock(spec=ProfileAccountService)
    view.account_service.settings = SimpleNamespace(limits=SimpleNamespace(links_max_per_user=5))
    view.account_service.resolve = AsyncMock(
        return_value=ResolvedAccount(
            "dota", "123", "Player", "https://steamcommunity.com/profiles/76561197960265851"
        )
    )
    view.account_service.save = AsyncMock()
    view.account_service.remove = AsyncMock()
    view._accounts = accounts or ProfileAccounts()
    view.builder.build_accounts = AsyncMock(return_value=view._accounts)
    view.active_tab = "accounts"
    view.message = MagicMock(edit=AsyncMock())
    view._render()
    return view


def _account_interaction(mock_interaction):
    mock_interaction.user.id = 1
    mock_interaction.response.edit_message = AsyncMock()
    mock_interaction.response.send_modal = AsyncMock()
    return mock_interaction


@pytest.mark.parametrize("full", [False, True])
def test_account_sections_serialize_with_owner_controls_and_limits(full):
    accounts = (
        ProfileAccounts(
            dota_ids=tuple(range(1, 6)),
            faceit=tuple(FaceitAccount(str(i), f"Player{i}") for i in range(5)),
        )
        if full
        else ProfileAccounts()
    )
    view = _account_view(accounts=accounts)
    buttons = [
        item
        for item in view.walk_children()
        if isinstance(item, discord.ui.Button)
        and (item.custom_id or "").startswith("profile_account:add:")
    ]
    assert len(buttons) == 2
    assert all(button.disabled == full for button in buttons)
    assert view.total_children_count <= 40
    assert "/link" not in str(view.to_components())
    assert "/cslink" not in str(view.to_components())


def test_foreign_profile_has_no_account_controls():
    view = _account_view(viewer_id=2, accounts=ProfileAccounts(dota_ids=(123,)))
    payload = str(view.to_components())
    assert "stratz.com/players/123" in payload
    assert "profile_account:" not in payload


async def test_add_button_opens_single_field_modal(mock_interaction):
    view = _account_view()
    interaction = _account_interaction(mock_interaction)
    button = next(
        item
        for item in view.walk_children()
        if getattr(item, "custom_id", "") == "profile_account:add:dota"
    )
    await button.callback(interaction)
    modal = interaction.response.send_modal.await_args.args[0]
    assert isinstance(modal, AccountLinkModal)
    assert len(modal.children) == 1


@pytest.mark.parametrize("public", [False, True])
async def test_public_profile_navigation_does_not_grant_link_management(mock_interaction, public):
    view = _account_view()
    view.public = public
    interaction = _account_interaction(mock_interaction)
    interaction.user.id = 2
    button = next(
        item
        for item in view.walk_children()
        if getattr(item, "custom_id", "") == "profile_account:add:dota"
    )
    with patch("utils.profile.views.safe_send", new_callable=AsyncMock):
        assert await view.interaction_check(interaction) is public
        await button.callback(interaction)
    interaction.response.send_modal.assert_not_awaited()
    view.account_service.save.assert_not_awaited()


async def test_modal_previews_account_without_saving(mock_interaction):
    view = _account_view()
    interaction = _account_interaction(mock_interaction)
    modal = AccountLinkModal(view, "dota")
    modal.account_input._value = "123"
    await modal.on_submit(interaction)
    view.account_service.resolve.assert_awaited_once_with("123", "dota")
    view.account_service.save.assert_not_awaited()
    preview = interaction.followup.send.await_args.kwargs["view"]
    assert isinstance(preview, AccountConfirmView)
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True


async def test_modal_error_never_opens_confirmation(mock_interaction):
    view = _account_view()
    view.account_service.resolve.side_effect = AccountLinkError("Аккаунт не найден")
    interaction = _account_interaction(mock_interaction)
    with patch("utils.profile.account_views.safe_send", new_callable=AsyncMock) as send:
        await AccountLinkModal(view, "cs").on_submit(interaction)
    send.assert_awaited_once_with(interaction, "Аккаунт не найден", ephemeral=True)
    view.account_service.save.assert_not_awaited()
    interaction.followup.send.assert_not_awaited()


async def test_double_confirmation_saves_once_and_refreshes_original(mock_interaction):
    view = _account_view()
    interaction = _account_interaction(mock_interaction)
    account = view.account_service.resolve.return_value
    view.builder.build_accounts.return_value = ProfileAccounts(
        dota_ids=(123,), dota_names={123: "Player"}
    )
    dialog = AccountConfirmView(view, account)
    await asyncio.gather(dialog.confirm(interaction), dialog.confirm(interaction))
    view.account_service.save.assert_awaited_once_with(1, account)
    view.message.edit.assert_awaited_once_with(view=view)
    assert "Player" in str(view.to_components())
    assert dialog.is_finished()


async def test_cancel_leaves_existing_links_untouched(mock_interaction):
    view = _account_view()
    interaction = _account_interaction(mock_interaction)
    dialog = AccountConfirmView(view, view.account_service.resolve.return_value)
    await dialog.cancel(interaction)
    await dialog.confirm(interaction)
    view.account_service.save.assert_not_awaited()
    view.account_service.remove.assert_not_awaited()


async def test_remove_select_requires_confirmation_for_exact_account(mock_interaction):
    view = _account_view(
        accounts=ProfileAccounts(dota_ids=(123,), faceit=(FaceitAccount("faceit-id", "Nickname"),))
    )
    interaction = _account_interaction(mock_interaction)
    dialog = AccountRemoveView(view, account_choices(view._accounts))
    select = next(item for item in dialog.walk_children() if isinstance(item, discord.ui.Select))
    select._values = ["1"]
    await select.callback(interaction)
    view.account_service.remove.assert_not_awaited()
    confirmation = interaction.response.edit_message.await_args.kwargs["view"]
    assert confirmation.remove is True
    assert confirmation.account.identifier == "faceit-id"
    await confirmation.confirm(interaction)
    view.account_service.remove.assert_awaited_once_with(1, confirmation.account)


@pytest.mark.parametrize("expired", [False, True])
async def test_foreign_or_expired_confirmation_cannot_change_links(mock_interaction, expired):
    view = _account_view()
    interaction = _account_interaction(mock_interaction)
    if expired:
        view.stop()
    else:
        interaction.user.id = 2
    dialog = AccountConfirmView(view, view.account_service.resolve.return_value)
    with patch("utils.profile.views.safe_send", new_callable=AsyncMock) as send:
        await dialog.confirm(interaction)
        await AccountLinkModal(view, "dota").on_submit(interaction)
    assert send.await_count == 2
    view.account_service.resolve.assert_not_awaited()
    view.account_service.save.assert_not_awaited()


async def test_duplicate_confirmation_keeps_profile_and_explains_error(mock_interaction):
    view = _account_view()
    interaction = _account_interaction(mock_interaction)
    view.account_service.save.side_effect = AccountLinkError("Этот аккаунт уже привязан")
    dialog = AccountConfirmView(view, view.account_service.resolve.return_value)
    with patch("utils.profile.account_views.safe_send", new_callable=AsyncMock) as send:
        await dialog.confirm(interaction)
    send.assert_awaited_once()
    view.message.edit.assert_not_awaited()


async def test_refresh_reads_new_links_after_other_panel_changes():
    view = _account_view(accounts=ProfileAccounts(dota_ids=(123,)))
    view.builder.build_accounts.return_value = ProfileAccounts(
        faceit=(FaceitAccount("new", "NewName"),)
    )
    await view.refresh_accounts()
    payload = str(view.to_components())
    assert "NewName" in payload
    assert "stratz.com/players/123" not in payload


async def test_expired_dialog_cannot_save_even_while_profile_is_open(mock_interaction):
    view = _account_view()
    interaction = _account_interaction(mock_interaction)
    dialog = AccountConfirmView(view, view.account_service.resolve.return_value)
    await dialog.on_timeout()
    with patch("utils.profile.account_views.safe_send", new_callable=AsyncMock) as send:
        await dialog.confirm(interaction)
    send.assert_awaited_once()
    view.account_service.save.assert_not_awaited()


async def test_confirmation_timeout_disables_mutating_buttons():
    view = _account_view()
    dialog = AccountConfirmView(view, view.account_service.resolve.return_value)
    dialog.message = MagicMock(edit=AsyncMock())
    await dialog.on_timeout()
    for item in dialog.walk_children():
        if isinstance(item, discord.ui.Button):
            assert item.disabled is (item.url is None)
    view.account_service.save.assert_not_awaited()


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
