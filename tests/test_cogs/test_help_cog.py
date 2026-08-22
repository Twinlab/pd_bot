"""Тесты динамической slash-справки."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from cogs.help import (
    HelpCog,
    HelpEntry,
    HelpView,
    build_help_catalog,
    build_help_embed,
    build_help_embeds,
    setup,
)


def _command(name: str, description: str) -> app_commands.Command:
    async def callback(_interaction: discord.Interaction) -> None:
        return None

    return app_commands.Command(
        name=name,
        description=description,
        callback=callback,
    )


def _profile_context_menu() -> app_commands.ContextMenu:
    class ProfileCog:
        async def callback(
            self,
            _interaction: discord.Interaction,
            _member: discord.Member,
        ) -> None:
            return None

    return app_commands.ContextMenu(
        name="Профиль",
        callback=ProfileCog().callback,
    )


def test_catalog_uses_registered_commands_and_skips_itself() -> None:
    catalog = build_help_catalog(
        [
            _command("profile", "Открыть профиль"),
            _command("lastmatch", "Последний матч"),
            _command("something_new", "Новая команда"),
            _command("help", "Справка"),
        ]
    )

    assert catalog["Профиль и статистика"][0].name == "profile"
    assert catalog["Dota 2"][0].name == "lastmatch"
    assert catalog["Прочее"][0].name == "something_new"
    assert all(entry.name != "help" for entries in catalog.values() for entry in entries)


def test_catalog_includes_context_menu_in_owning_cog_category() -> None:
    catalog = build_help_catalog([_profile_context_menu()])

    entry = catalog["Профиль и статистика"][0]
    assert entry.name == "Профиль"
    assert entry.usage == "ПКМ → Профиль"
    assert entry.description == "Контекстное меню пользователя"

    embed = build_help_embed("Профиль и статистика", (entry,))
    assert "`ПКМ → Профиль`" in embed.description
    assert "`/Профиль`" not in embed.description


def test_help_embed_escapes_mentions() -> None:
    embed = build_help_embed(
        "Прочее",
        (HelpEntry("test", "Позвать @everyone и @here"),),
    )

    assert embed.description is not None
    assert "@everyone" not in embed.description
    assert "@here" not in embed.description
    assert "`/test`" in embed.description


def test_restricted_command_has_lock() -> None:
    command = _command("shutdown", "Остановить бота")
    command.default_permissions = discord.Permissions(administrator=True)

    catalog = build_help_catalog([command])
    entry = catalog["Прочее"][0]

    assert entry.restricted is True
    assert "🔒 `/shutdown`" in build_help_embed("Прочее", (entry,)).description


def test_long_category_is_paginated_without_losing_commands() -> None:
    entries = tuple(
        HelpEntry(f"command-{index}", f"Описание {index} " + "x" * 180)
        for index in range(40)
    )

    embeds = build_help_embeds("Прочее", entries)

    assert len(embeds) > 1
    rendered = "\n".join(embed.description or "" for embed in embeds)
    assert all(f"`/command-{index}`" in rendered for index in range(40))
    assert all(len(embed.description or "") <= 4096 for embed in embeds)


@pytest.mark.asyncio
async def test_view_switches_category_in_place() -> None:
    catalog = {
        "Dota 2": (HelpEntry("lastmatch", "Матч"),),
        "Музыка": (HelpEntry("play", "Музыка"),),
    }
    view = HelpView(owner_id=10, catalog=catalog)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()

    await view.select_category(interaction, "Музыка")

    assert view.category == "Музыка"
    interaction.response.edit_message.assert_awaited_once()
    assert interaction.response.edit_message.await_args.kwargs["view"] is view


@pytest.mark.asyncio
async def test_view_rejects_another_user() -> None:
    view = HelpView(
        owner_id=10,
        catalog={"Прочее": (HelpEntry("test", "Тест"),)},
    )
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(id=20)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    allowed = await view.interaction_check(interaction)

    assert allowed is False
    interaction.response.send_message.assert_awaited_once_with(
        "Это меню открыто не тобой.",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_view_pages_long_category() -> None:
    entries = tuple(HelpEntry(f"command-{index}", "x" * 250) for index in range(40))
    view = HelpView(owner_id=10, catalog={"Прочее": entries})
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()

    await view.change_page(interaction, 1)

    assert view.page == 1
    interaction.response.edit_message.assert_awaited_once_with(embed=view.embed, view=view)


@pytest.mark.asyncio
async def test_help_command_uses_guild_tree_and_is_ephemeral() -> None:
    bot = MagicMock(spec=commands.Bot)
    bot.tree = MagicMock(spec=app_commands.CommandTree)
    bot.tree.get_commands.return_value = [_command("profile", "Открыть профиль")]
    cog = HelpCog(bot)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.user = MagicMock(id=10)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.help_command.callback(cog, interaction)  # type: ignore[call-arg]

    bot.tree.get_commands.assert_called_once_with(guild=interaction.guild)
    kwargs = interaction.response.send_message.await_args.kwargs
    assert kwargs["ephemeral"] is True
    assert isinstance(kwargs["view"], HelpView)
    assert "profile" in kwargs["embed"].description


@pytest.mark.asyncio
async def test_setup_adds_help_cog() -> None:
    bot = MagicMock(spec=commands.Bot)
    bot.add_cog = AsyncMock()

    await setup(bot)

    added = bot.add_cog.await_args.args[0]
    assert isinstance(added, HelpCog)
