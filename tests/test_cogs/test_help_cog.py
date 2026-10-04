"""Тесты личной CV2-справки, прав доступа и ссылок зарегистрированных команд."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from cogs.help import (
    HelpCog,
    HelpEntry,
    HelpSectionButton,
    HelpView,
    build_help_catalog,
    build_help_pages,
    setup,
)
from utils.ui.testing import joined_text


def _command(name: str, description: str = "Описание", cog_name: str = "") -> app_commands.Command:
    async def callback(_interaction: discord.Interaction) -> None:
        return None

    command = app_commands.Command(name=name, description=description, callback=callback)
    if cog_name:
        command.binding = type(cog_name, (), {})()
    return command


def _owner_command() -> app_commands.Command:
    @commands.hybrid_command(name="restart")
    @app_commands.default_permissions(administrator=True)
    @commands.is_owner()
    async def restart(ctx: commands.Context) -> None:
        pass

    assert restart.app_command is not None
    return restart.app_command


def _interaction(user_id: int = 10) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(id=user_id)
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 55
    interaction.permissions = discord.Permissions.none()
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = False
    interaction.edit_original_response = AsyncMock()
    interaction.followup = MagicMock()
    message = MagicMock(spec=discord.WebhookMessage)
    message.edit = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=message)
    return interaction


def _bot(top_level: list) -> MagicMock:
    bot = MagicMock(spec=commands.Bot)
    bot.tree = MagicMock(spec=app_commands.CommandTree)
    bot.tree.get_commands.return_value = top_level
    bot.tree.fetch_commands = AsyncMock(return_value=[])
    bot.is_owner = AsyncMock(return_value=False)
    return bot


def _synced(name: str, command_id: int, *, context_menu: bool = False) -> MagicMock:
    command = MagicMock(spec=app_commands.AppCommand)
    command.name = name
    command.id = command_id
    command.type = (
        discord.AppCommandType.user if context_menu else discord.AppCommandType.chat_input
    )
    return command


def _catalog_names(catalog: dict) -> set[str]:
    return {entry.name for entries in catalog.values() for entry in entries}


def test_catalog_uses_registered_commands_and_skips_itself() -> None:
    catalog = build_help_catalog(
        [
            _command("profile"),
            _command("lastmatch"),
            _command("something_new"),
            _command("help"),
        ],
        permissions=discord.Permissions.none(),
    )

    assert catalog["Профиль и статистика"][0].name == "profile"
    assert catalog["Dota 2"][0].name == "lastmatch"
    assert _catalog_names(catalog) == {"profile", "lastmatch", "something_new"}


def test_context_menu_has_apps_hint_not_a_slash_mention() -> None:
    class ProfileCog:
        async def callback(
            self, _interaction: discord.Interaction, _member: discord.Member
        ) -> None:
            pass

    menu = app_commands.ContextMenu(name="Профиль", callback=ProfileCog().callback)
    catalog = build_help_catalog(
        [menu], permissions=discord.Permissions.none(), command_ids={"Профиль": 777}
    )
    text = build_help_pages(catalog["Профиль и статистика"])[0]

    assert "Меню пользователя → Приложения → Профиль" in text
    assert "</" not in text
    assert "/Профиль" not in text


@pytest.mark.parametrize(
    ("permissions", "expected"),
    [
        (discord.Permissions.none(), {"profile"}),
        (discord.Permissions(manage_messages=True), {"profile", "clear"}),
        (discord.Permissions(kick_members=True), {"profile", "kick"}),
        (discord.Permissions(administrator=True), {"profile", "clear", "kick", "hidden"}),
    ],
)
def test_permissions_filter_commands_not_entire_categories(permissions, expected) -> None:
    clear = _command("clear", cog_name="AdminCog")
    clear.default_permissions = discord.Permissions(manage_messages=True)
    kick = _command("kick", cog_name="AdminCog")
    kick.default_permissions = discord.Permissions(kick_members=True)
    hidden = _command("hidden")
    hidden.default_permissions = discord.Permissions.none()

    catalog = build_help_catalog(
        [_command("profile"), clear, kick, hidden], permissions=permissions
    )

    assert _catalog_names(catalog) == expected


@pytest.mark.parametrize("is_owner", [False, True])
def test_owner_restriction_also_applies_to_administrators(is_owner: bool) -> None:
    catalog = build_help_catalog(
        [_owner_command()],
        permissions=discord.Permissions(administrator=True),
        is_owner=is_owner,
    )

    assert ("restart" in _catalog_names(catalog)) is is_owner


def test_filter_never_executes_arbitrary_command_checks() -> None:
    command = _command("example")
    check = AsyncMock(side_effect=AssertionError("Проверку нельзя вызывать"))
    command.add_check(check)

    assert build_help_catalog([command], permissions=discord.Permissions.none())
    check.assert_not_called()


def test_group_permissions_and_registered_root_id_apply_to_subcommand() -> None:
    group = app_commands.Group(
        name="admin",
        description="Настройки",
        default_permissions=discord.Permissions(administrator=True),
    )
    group.add_command(_command("inspect"))
    assert not build_help_catalog([group], permissions=discord.Permissions.none())

    catalog = build_help_catalog(
        [group],
        permissions=discord.Permissions(administrator=True),
        command_ids={"admin": 123456},
    )

    assert "</admin inspect:123456>" in build_help_pages(catalog["Прочее"])[0]


def test_guild_only_command_is_hidden_in_direct_messages() -> None:
    command = _command("profile")
    command.guild_only = True
    assert not build_help_catalog(
        [command], permissions=discord.Permissions.none(), in_guild=False
    )


def test_real_mentions_plain_fallback_and_escaped_descriptions() -> None:
    text = build_help_pages(
        (
            HelpEntry("profile", "Позвать @everyone и @here", command_id=12345),
            HelpEntry("party", "Собрать компанию"),
        )
    )[0]

    assert "</profile:12345>" in text
    assert "/party" in text
    assert "</party:" not in text
    assert "@everyone" not in text
    assert "@here" not in text


def test_pagination_keeps_every_command_once() -> None:
    entries = tuple(
        HelpEntry(f"command-{index}", f"Описание {index} " + "x" * 100)
        for index in range(70)
    )
    pages = build_help_pages(entries)
    rendered = "\n".join(pages)

    assert len(pages) > 1
    assert all(
        rendered.count(f"{chr(96)}/command-{index}{chr(96)}") == 1
        for index in range(70)
    )
    assert all(len(page) <= 3000 for page in pages)


@pytest.mark.asyncio
async def test_home_has_four_scenarios_and_live_category_menu() -> None:
    catalog = {
        category: (HelpEntry(name, "Тест"),)
        for category, name in [
            ("Профиль и статистика", "profile"),
            ("Сборы", "party"),
            ("Музыка", "play"),
            ("Развлечения", "tyan"),
        ]
    }
    view = HelpView(owner_id=10, catalog=catalog)

    assert view.has_components_v2()
    assert view.category is None
    assert "Чем займёмся" in joined_text(view)
    sections = [
        child for child in view.walk_children() if isinstance(child, HelpSectionButton)
    ]
    assert len(sections) == 4
    assert {section.category for section in sections} == set(catalog)
    assert all(section.label == "Открыть раздел" for section in sections)
    assert view.content_length() <= 4000
    assert view.to_components()[0]["type"] == discord.ComponentType.container.value


@pytest.mark.asyncio
async def test_view_switches_category_and_returns_home_in_place() -> None:
    view = HelpView(owner_id=10, catalog={"Музыка": (HelpEntry("play", "Музыка"),)})
    interaction = _interaction()
    await view.select_category(interaction, "Музыка")

    assert view.category == "Музыка"
    assert "/play" in joined_text(view)
    interaction.response.defer.assert_awaited_once()
    interaction.edit_original_response.assert_awaited_once_with(view=view)

    await view.select_category(interaction, None)
    assert view.category is None
    assert "Чем займёмся" in joined_text(view)


@pytest.mark.asyncio
async def test_missing_category_has_private_error_without_changing_view() -> None:
    view = HelpView(owner_id=10, catalog={"Прочее": (HelpEntry("test", "Тест"),)})
    interaction = _interaction()
    await view.select_category(interaction, "Не существует")

    assert view.category is None
    interaction.response.send_message.assert_awaited_once_with(
        "Раздел не найден.", ephemeral=True
    )
    interaction.edit_original_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_view_rejects_another_user() -> None:
    view = HelpView(owner_id=10, catalog={"Прочее": (HelpEntry("test", "Тест"),)})
    interaction = _interaction(user_id=20)

    assert await view.interaction_check(interaction) is False
    interaction.response.send_message.assert_awaited_once_with(
        "Это меню открыто не тобой.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_every_cv2_page_and_timeout_notice_fit_total_text_limit() -> None:
    entries = tuple(
        HelpEntry(f"command-{index}", "x" * 100, command_id=123456789012345678)
        for index in range(70)
    )
    view = HelpView(owner_id=10, catalog={"Музыка": entries})
    interaction = _interaction()
    await view.select_category(interaction, "Музыка")

    for _ in range(len(build_help_pages(entries))):
        assert view.content_length() <= 4000
        assert view.to_components()[0]["type"] == discord.ComponentType.container.value
        await view.change_page(interaction, 1)
    last_page = view.page
    await view.change_page(interaction, 99)
    assert view.page == last_page
    await view.change_page(interaction, -99)
    assert view.page == 0
    await view.on_timeout()
    assert view.content_length() <= 4000


@pytest.mark.asyncio
async def test_timeout_removes_controls_and_edits_delivered_message() -> None:
    view = HelpView(owner_id=10, catalog={"Прочее": (HelpEntry("test", "Тест"),)})
    view.message = MagicMock(spec=discord.Message)
    view.message.edit = AsyncMock()

    await view.on_timeout()

    assert "/help" in joined_text(view)
    assert not any(
        isinstance(child, (discord.ui.Button, discord.ui.Select))
        for child in view.walk_children()
    )
    view.message.edit.assert_awaited_once_with(view=view)
    assert await view.interaction_check(_interaction()) is False


@pytest.mark.asyncio
async def test_timeout_edits_message_from_latest_interaction() -> None:
    view = HelpView(owner_id=10, catalog={"Прочее": (HelpEntry("test", "Тест"),)})
    original_message = MagicMock(spec=discord.Message)
    original_message.edit = AsyncMock()
    view.message = original_message
    interaction = _interaction()
    latest_message = interaction.edit_original_response.return_value

    await view.select_category(interaction, "Прочее")
    await view.on_timeout()

    original_message.edit.assert_not_awaited()
    latest_message.edit.assert_awaited_once_with(view=view)


@pytest.mark.asyncio
async def test_timeout_tolerates_deleted_message() -> None:
    view = HelpView(owner_id=10, catalog={"Прочее": (HelpEntry("test", "Тест"),)})
    view.message = MagicMock(spec=discord.Message)
    view.message.edit = AsyncMock(side_effect=discord.NotFound(MagicMock(), "Удалено"))

    await view.on_timeout()

    assert "Меню закрыто" in joined_text(view)


@pytest.mark.asyncio
@pytest.mark.parametrize("responded", [False, True])
async def test_component_error_returns_private_incident_id(responded: bool) -> None:
    view = HelpView(owner_id=10, catalog={"Прочее": (HelpEntry("test", "Тест"),)})
    interaction = _interaction()
    interaction.response.is_done.return_value = responded
    with patch("cogs.help.new_incident_id", return_value="ABC123"):
        await view.on_error(interaction, RuntimeError("Внутренние детали"), discord.ui.Button())

    sender = interaction.followup.send if responded else interaction.response.send_message
    assert sender.await_args.kwargs["ephemeral"] is True
    assert "ABC123" in sender.await_args.args[0]
    assert "Внутренние детали" not in sender.await_args.args[0]


@pytest.mark.asyncio
async def test_help_uses_guild_ids_cached_after_private_defer() -> None:
    bot = _bot([_command("profile")])
    bot.tree.fetch_commands.return_value = [
        _synced("profile", 12345),
        _synced("Профиль", 999, context_menu=True),
    ]
    interaction = _interaction()
    cog = HelpCog(bot)

    async def fetch(*, guild):
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        assert guild is interaction.guild
        return bot.tree.fetch_commands.return_value

    bot.tree.fetch_commands.side_effect = fetch
    await cog.help_command.callback(cog, interaction)  # type: ignore[call-arg]
    kwargs = interaction.followup.send.await_args.kwargs
    view = kwargs["view"]
    assert kwargs["ephemeral"] is True
    assert "content" not in kwargs and "embed" not in kwargs
    assert isinstance(view, HelpView)
    assert view.message is interaction.followup.send.return_value
    assert view.catalog["Профиль и статистика"][0].command_id == 12345
    assert cog._command_ids[55] == {"profile": 12345}

    await cog.help_command.callback(cog, _interaction())  # type: ignore[call-arg]
    bot.tree.fetch_commands.assert_awaited_once()


@pytest.mark.asyncio
async def test_global_tree_fallback_fetches_global_command_ids() -> None:
    bot = _bot([_command("profile")])
    bot.tree.get_commands.side_effect = lambda **kwargs: [] if kwargs.get("guild") else [
        _command("profile")
    ]
    bot.tree.fetch_commands.return_value = [_synced("profile", 222)]
    cog = HelpCog(bot)

    await cog.help_command.callback(cog, _interaction())  # type: ignore[call-arg]

    bot.tree.fetch_commands.assert_awaited_once_with(guild=None)


@pytest.mark.asyncio
async def test_fetch_failure_falls_back_and_retries_after_backoff() -> None:
    bot = _bot([_command("profile")])
    bot.tree.fetch_commands.side_effect = [
        discord.HTTPException(MagicMock(), "Недоступно"),
        [_synced("profile", 789)],
    ]
    cog = HelpCog(bot)
    with patch("cogs.help.time.monotonic", return_value=100):
        await cog.help_command.callback(cog, _interaction())  # type: ignore[call-arg]
        await cog.help_command.callback(cog, _interaction())  # type: ignore[call-arg]
    assert bot.tree.fetch_commands.await_count == 1
    with patch("cogs.help.time.monotonic", return_value=161):
        interaction = _interaction()
        await cog.help_command.callback(cog, interaction)  # type: ignore[call-arg]
    view = interaction.followup.send.await_args.kwargs["view"]
    assert view.catalog["Профиль и статистика"][0].command_id == 789


@pytest.mark.asyncio
async def test_owner_lookup_failure_keeps_help_usable_and_hides_restart() -> None:
    bot = _bot([_command("profile"), _owner_command()])
    bot.is_owner.side_effect = discord.HTTPException(MagicMock(), "Недоступно")
    interaction = _interaction()
    interaction.permissions = discord.Permissions(administrator=True)
    cog = HelpCog(bot)

    await cog.help_command.callback(cog, interaction)  # type: ignore[call-arg]

    view = interaction.followup.send.await_args.kwargs["view"]
    assert _catalog_names(view.catalog) == {"profile"}


@pytest.mark.asyncio
async def test_empty_visible_catalog_gives_private_message() -> None:
    bot = _bot([_owner_command()])
    interaction = _interaction()
    cog = HelpCog(bot)

    await cog.help_command.callback(cog, interaction)  # type: ignore[call-arg]

    interaction.followup.send.assert_awaited_once_with(
        "Список команд пока недоступен.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_setup_adds_help_cog() -> None:
    bot = _bot([])
    bot.add_cog = AsyncMock()

    await setup(bot)

    assert isinstance(bot.add_cog.await_args.args[0], HelpCog)
