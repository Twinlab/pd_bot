"""Тесты реального Discord-view для отчётов активности."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from utils.activity.views import DISCORD_MESSAGE_MAX_LENGTH, ActivityView


def _build_bot_with_guild(member_names: dict[int, str]) -> MagicMock:
    """Создаёт single-guild бот с участниками из переданного словаря."""
    members: dict[int, MagicMock] = {}
    for user_id, name in member_names.items():
        member = MagicMock(spec=discord.Member)
        member.id = user_id
        member.name = name
        members[user_id] = member

    guild = MagicMock(spec=discord.Guild)
    guild.get_member.side_effect = members.get

    bot = MagicMock(spec=discord.Client)
    bot.guilds = [guild]
    return bot


def _button(view: ActivityView, custom_id: str) -> discord.ui.Button:
    item = next(item for item in view.children if getattr(item, "custom_id", None) == custom_id)
    assert isinstance(item, discord.ui.Button)
    return item


@pytest.fixture
def activity_data() -> dict[int, dict[str, int]]:
    return {
        1: {"Game1": 3600, "Game2": 1800},
        2: {"Game1": 7200},
        3: {"Game3": 5400, "Game2": 900},
    }


@pytest.fixture
def bot() -> MagicMock:
    return _build_bot_with_guild({1: "Charlie", 2: "Alice", 3: "Bob"})


async def test_prepare_data_filters_zero_values_and_builds_both_modes(
    bot: MagicMock,
    activity_data: dict[int, dict[str, int]],
) -> None:
    activity_data[1]["Ignored"] = 0
    activity_data[4] = {"Also ignored": 0}

    view = ActivityView(bot, activity_data)

    assert view.users_data == {
        1: {"Game1": 3600, "Game2": 1800},
        2: {"Game1": 7200},
        3: {"Game3": 5400, "Game2": 900},
    }
    assert view.user_ids == [2, 3, 1]
    assert view.games_data["Game1"] == {1: 3600, 2: 7200}
    assert view.games_data["Game2"] == {1: 1800, 3: 900}
    assert "Ignored" not in view.games_data
    assert view.games_list[0] == "Game1"


async def test_content_uses_real_members_games_summary_and_date(
    bot: MagicMock,
    activity_data: dict[int, dict[str, int]],
) -> None:
    view = ActivityView(bot, activity_data, report_type="command", date_str=" (01.05.2025)")

    users_content = view.get_current_content()
    assert "Alice" in users_content
    assert "Bob" in users_content
    assert "Charlie" in users_content
    assert "Game1 (2h)" in users_content
    assert "Game3 (1h 30m)" in users_content
    assert "5h 15m" in users_content
    assert "01.05.2025" in users_content
    assert "1/1" in users_content

    view.view_mode = "games"
    view._recalculate_max_pages()
    games_content = view.get_current_content()
    assert "Game1" in games_content
    assert "Game2" in games_content
    assert "Game3" in games_content
    assert "3h" in games_content
    assert "45m" in games_content
    assert "1h 30m" in games_content


async def test_empty_data_has_one_page_and_explanatory_content(bot: MagicMock) -> None:
    view = ActivityView(bot, {})

    assert view.users_data == {}
    assert view.games_data == {}
    assert view.max_pages == 1
    assert "нет данных" in view.get_current_content().lower()

    view.view_mode = "games"
    view._recalculate_max_pages()
    assert view.max_pages == 1
    assert "нет данных" in view.get_current_content().lower()


async def test_context_guild_takes_precedence_over_bot_guild() -> None:
    bot = _build_bot_with_guild({1: "Bot member"})
    context_guild = MagicMock(spec=discord.Guild)
    context_member = MagicMock(spec=discord.Member)
    context_member.name = "Context member"
    context_guild.get_member.return_value = context_member
    ctx = MagicMock()
    ctx.guild = context_guild

    view = ActivityView(bot, {1: {"Game": 60}}, ctx=ctx)

    assert view._get_guild() is context_guild
    assert "Context member" in view.get_current_content()


async def test_guild_fallback_and_missing_member_are_handled() -> None:
    bot = MagicMock(spec=discord.Client)
    bot.guilds = []

    view = ActivityView(bot, {999: {"Game": 3600}, 2: {"Game": 120}})

    assert view._get_guild() is None
    assert view.user_ids == [2, 999]
    assert "999" in view.get_current_content()


async def test_member_without_name_uses_stable_fallback() -> None:
    guild = MagicMock(spec=discord.Guild)
    member = MagicMock(spec=discord.Member)
    member.name = None
    guild.get_member.return_value = member
    bot = MagicMock(spec=discord.Client)
    bot.guilds = [guild]

    view = ActivityView(bot, {1: {"Game": 3600}})

    assert view.user_ids == [1]
    assert "1" in view.get_current_content()


async def test_pages_cover_every_item_once() -> None:
    names = {user_id: f"User{user_id:02d}" for user_id in range(1, 31)}
    data = {
        user_id: {f"Game{game_id}": 1200 + game_id * 60 for game_id in range(1, 6)}
        for user_id in names
    }
    view = ActivityView(_build_bot_with_guild(names), data)

    user_ids = [user_id for page in view._user_pages for user_id in page]
    game_names = [game for page in view._game_pages for game in page]

    assert sorted(user_ids) == sorted(view.user_ids)
    assert len(user_ids) == len(set(user_ids))
    assert sorted(game_names) == sorted(view._game_lines)
    assert len(game_names) == len(set(game_names))


async def test_every_regular_page_stays_under_discord_limit() -> None:
    names = {user_id: f"LongUsername_{user_id:02d}" for user_id in range(1, 31)}
    data = {
        user_id: {
            f"VeryLongGameName_{game_id}": 3600 + game_id * 100
            for game_id in range(1, 7)
        }
        for user_id in names
    }
    view = ActivityView(_build_bot_with_guild(names), data)

    assert view.max_pages >= 2
    for mode in ("users", "games"):
        view.view_mode = mode
        view.current_page = 0
        view._recalculate_max_pages()
        for page in range(view.max_pages):
            view.current_page = page
            assert len(view.get_current_content()) <= DISCORD_MESSAGE_MAX_LENGTH


async def test_single_oversized_item_is_not_silently_dropped() -> None:
    data = {1: {f"GameWithReallyLongTitle_{index}": 1800 for index in range(1, 51)}}
    view = ActivityView(_build_bot_with_guild({1: "VeryLongPlayerNickname"}), data)

    content = view.get_current_content()

    assert "VeryLongPlayerNickname" in content
    assert "GameWithReallyLongTitle_1" in content


async def test_max_items_per_page_is_enforced_when_data_is_reprepared() -> None:
    data = {user_id: {"Game": 60} for user_id in range(1, 6)}
    view = ActivityView(_build_bot_with_guild({uid: str(uid) for uid in data}), data)
    view.max_items_per_page = 2

    view.prepare_data()

    assert [len(page) for page in view._user_pages] == [2, 2, 1]
    assert view.max_pages == 3


async def test_recalculate_resets_out_of_range_page(bot: MagicMock) -> None:
    view = ActivityView(bot, {1: {"Game": 60}})
    view.current_page = 99

    view._recalculate_max_pages()

    assert view.current_page == 0


async def test_button_state_matches_current_page_and_mode() -> None:
    data = {user_id: {"Game": 60} for user_id in range(1, 4)}
    view = ActivityView(_build_bot_with_guild({uid: str(uid) for uid in data}), data)
    view.max_items_per_page = 1
    view.prepare_data()
    view._update_buttons()

    assert _button(view, "prev_button").disabled is True
    assert _button(view, "next_button").disabled is False
    assert _button(view, "toggle_mode_button").label is not None

    view.current_page = view.max_pages - 1
    view._update_buttons()
    assert _button(view, "prev_button").disabled is False
    assert _button(view, "next_button").disabled is True

    old_label = _button(view, "toggle_mode_button").label
    view.view_mode = "games"
    view._recalculate_max_pages()
    view._update_buttons()
    assert _button(view, "toggle_mode_button").label != old_label


async def test_previous_and_next_buttons_edit_message(bot: MagicMock) -> None:
    data = {user_id: {"Game": 60} for user_id in range(1, 4)}
    view = ActivityView(bot, data)
    view.max_items_per_page = 1
    view.prepare_data()
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()

    await ActivityView.next_button.__get__(view)(interaction, _button(view, "next_button"))
    assert view.current_page == 1
    interaction.response.edit_message.assert_awaited_once()

    interaction.response.edit_message.reset_mock()
    await ActivityView.previous_button.__get__(view)(interaction, _button(view, "prev_button"))
    assert view.current_page == 0
    interaction.response.edit_message.assert_awaited_once()


async def test_boundary_buttons_defer_without_changing_page(bot: MagicMock) -> None:
    view = ActivityView(bot, {1: {"Game": 60}})
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()

    await ActivityView.previous_button.__get__(view)(interaction, _button(view, "prev_button"))
    await ActivityView.next_button.__get__(view)(interaction, _button(view, "next_button"))

    assert view.current_page == 0
    assert interaction.response.defer.await_count == 2
    interaction.response.edit_message.assert_not_awaited()


async def test_toggle_button_switches_mode_and_resets_page(bot: MagicMock) -> None:
    view = ActivityView(bot, {1: {"Game": 60}})
    view.current_page = 5
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.edit_message = AsyncMock()

    await ActivityView.toggle_mode.__get__(view)(
        interaction,
        _button(view, "toggle_mode_button"),
    )

    assert view.view_mode == "games"
    assert view.current_page == 0
    interaction.response.edit_message.assert_awaited_once()


async def test_timeout_disables_components_and_updates_message(bot: MagicMock) -> None:
    view = ActivityView(bot, {})
    view.message = MagicMock(spec=discord.Message)
    view.message.edit = AsyncMock()

    await view.on_timeout()

    assert all(getattr(item, "disabled", False) for item in view.children)
    view.message.edit.assert_awaited_once_with(view=view)


async def test_timeout_without_message_needs_no_edit(bot: MagicMock) -> None:
    view = ActivityView(bot, {})

    await view.on_timeout()

    assert all(getattr(item, "disabled", False) for item in view.children)


async def test_timeout_ignores_deleted_message(bot: MagicMock) -> None:
    view = ActivityView(bot, {})
    view.message = MagicMock(spec=discord.Message)
    response = MagicMock()
    response.status = 404
    response.reason = "Not Found"
    view.message.edit = AsyncMock(side_effect=discord.HTTPException(response, "deleted"))

    await view.on_timeout()

    view.message.edit.assert_awaited_once_with(view=view)
