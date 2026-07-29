"""Тесты Components V2-представления профиля."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

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


def _view() -> ProfileView:
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
        requester_id=1,
        target=_member(),
        builder=MagicMock(spec=ProfileStatsBuilder),
        stats=stats,
        eligible_user_ids={1},
    )


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
async def test_only_requester_can_switch_profile_tabs() -> None:
    view = _view()
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = 2
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    allowed = await view.interaction_check(interaction)

    assert allowed is False
    interaction.response.send_message.assert_awaited_once_with(
        "Это профиль, открытый другим пользователем. Используйте `/profile`.",
        ephemeral=True,
    )
