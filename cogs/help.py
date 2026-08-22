"""Динамическая справка по доступным slash-командам бота."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.cogs.help")

HELP_DESCRIPTION_LIMIT = 3900

_CATEGORY_ORDER = (
    "Профиль и статистика",
    "Dota 2",
    "Counter-Strike 2",
    "Музыка",
    "Сборы",
    "Развлечения",
    "Сервер и роли",
    "Администрирование",
    "Прочее",
)

_CATEGORY_BY_COG = {
    "ProfileCog": "Профиль и статистика",
    "ActivityTracker": "Профиль и статистика",
    "UserStatsTracker": "Профиль и статистика",
    "TopReactionsCog": "Профиль и статистика",
    "LastMatchCog": "Dota 2",
    "LinksCog": "Dota 2",
    "CsLastMatchCog": "Counter-Strike 2",
    "CsLinksCog": "Counter-Strike 2",
    "MusicCog": "Музыка",
    "PartyCog": "Сборы",
    "FunCog": "Развлечения",
    "AnimeCog": "Развлечения",
    "RoleReactionCog": "Сервер и роли",
    "TwitchCog": "Сервер и роли",
    "AdminCog": "Администрирование",
    "LoggingCog": "Администрирование",
}

_CATEGORY_BY_COMMAND = {
    "profile": "Профиль и статистика",
    "lastmatch": "Dota 2",
    "link": "Dota 2",
    "unlink": "Dota 2",
    "links": "Dota 2",
    "cslastmatch": "Counter-Strike 2",
    "cslink": "Counter-Strike 2",
    "csunlink": "Counter-Strike 2",
    "cslinks": "Counter-Strike 2",
    "party": "Сборы",
    "party_cancel": "Сборы",
    "party_block": "Администрирование",
    "party_unblock": "Администрирование",
    "party_blocklist": "Администрирование",
}


@dataclass(frozen=True, slots=True)
class HelpEntry:
    """Одна строка справочника команд."""

    name: str
    description: str
    usage: str | None = None
    restricted: bool = False


HelpCatalog = dict[str, tuple[HelpEntry, ...]]
HelpCommand = app_commands.Command[Any, ..., Any] | app_commands.ContextMenu
TopLevelCommand = HelpCommand | app_commands.Group


def _category_for(command: HelpCommand) -> str:
    binding = getattr(command, "binding", None)
    if binding is None and isinstance(command, app_commands.ContextMenu):
        binding = getattr(command.callback, "__self__", None)
    cog_name = type(binding).__name__ if binding is not None else ""
    if cog_name in _CATEGORY_BY_COG:
        return _CATEGORY_BY_COG[cog_name]
    return _CATEGORY_BY_COMMAND.get(command.name, "Прочее")


def _walk_commands(top_level: list[TopLevelCommand]) -> list[HelpCommand]:
    result: list[HelpCommand] = []
    for command in top_level:
        if isinstance(command, app_commands.Group):
            result.extend(
                nested
                for nested in command.walk_commands()
                if isinstance(nested, app_commands.Command)
            )
        else:
            result.append(command)
    return result


def build_help_catalog(top_level: list[TopLevelCommand]) -> HelpCatalog:
    """Группирует зарегистрированные команды и контекстные действия."""
    grouped: dict[str, list[HelpEntry]] = defaultdict(list)
    for command in _walk_commands(top_level):
        if isinstance(command, app_commands.Command) and command.qualified_name == "help":
            continue

        category = _category_for(command)
        restricted = category == "Администрирование" or command.default_permissions is not None
        if isinstance(command, app_commands.ContextMenu):
            target = "пользователя" if command.type is discord.AppCommandType.user else "сообщения"
            entry = HelpEntry(
                name=command.name,
                description=f"Контекстное меню {target}",
                usage=f"ПКМ → {command.name}",
                restricted=restricted,
            )
        else:
            entry = HelpEntry(
                name=command.qualified_name,
                description=command.description.strip() or "Без описания",
                restricted=restricted,
            )
        grouped[category].append(entry)

    catalog: HelpCatalog = {}
    for category in _CATEGORY_ORDER:
        entries = grouped.get(category)
        if entries:
            catalog[category] = tuple(sorted(entries, key=lambda entry: entry.name))
    return catalog


def _entry_line(entry: HelpEntry) -> str:
    description = discord.utils.escape_mentions(entry.description)
    usage = discord.utils.escape_mentions(entry.usage or f"/{entry.name}")
    lock = "🔒 " if entry.restricted else ""
    return f"{lock}`{usage}` — {description}"


def build_help_embeds(
    category: str,
    entries: tuple[HelpEntry, ...],
) -> tuple[discord.Embed, ...]:
    """Разбивает категорию на embed-страницы без потери команд."""
    page_lines: list[list[str]] = [[]]
    page_length = 0
    for entry in entries:
        line = _entry_line(entry)
        if page_lines[-1] and page_length + len(line) + 1 > HELP_DESCRIPTION_LIMIT:
            page_lines.append([])
            page_length = 0
        page_lines[-1].append(line)
        page_length += len(line) + 1

    page_count = len(page_lines)
    embeds: list[discord.Embed] = []
    for page_number, lines in enumerate(page_lines, start=1):
        embed = discord.Embed(
            title=f"Справка · {category}",
            description="\n".join(lines) or "В этой категории пока нет команд.",
            color=discord.Color.blurple(),
        )
        footer = "Выбери другую категорию в меню ниже"
        if page_count > 1:
            footer = f"Страница {page_number}/{page_count} · {footer}"
        embeds.append(embed.set_footer(text=footer))
    return tuple(embeds)


def build_help_embed(category: str, entries: tuple[HelpEntry, ...]) -> discord.Embed:
    """Собирает первую embed-страницу категории для простых вызовов."""
    return build_help_embeds(category, entries)[0]


class HelpCategorySelect(discord.ui.Select["HelpView"]):
    """Переключатель разделов справки."""

    def __init__(self, catalog: HelpCatalog, selected: str) -> None:
        super().__init__(
            placeholder="Раздел справки",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=category,
                    value=category,
                    description=f"Команд: {len(entries)}",
                    default=category == selected,
                )
                for category, entries in catalog.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.select_category(interaction, self.values[0])


class HelpPageButton(discord.ui.Button["HelpView"]):
    """Переключает страницу внутри длинной категории."""

    def __init__(self, delta: int, *, disabled: bool) -> None:
        super().__init__(
            label="Назад" if delta < 0 else "Далее",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
        self.delta = delta

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.change_page(interaction, self.delta)


class HelpView(discord.ui.View):
    """Приватный переключаемый справочник команд."""

    def __init__(self, *, owner_id: int, catalog: HelpCatalog) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.catalog = catalog
        self.category = next(iter(catalog))
        self.page = 0
        self._pages = {
            category: build_help_embeds(category, entries) for category, entries in catalog.items()
        }
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        self.clear_items()
        self.add_item(HelpCategorySelect(self.catalog, self.category))
        page_count = len(self._pages[self.category])
        if page_count > 1:
            self.add_item(HelpPageButton(-1, disabled=self.page == 0))
            self.add_item(HelpPageButton(1, disabled=self.page >= page_count - 1))

    @property
    def embed(self) -> discord.Embed:
        """Возвращает текущую страницу справки."""
        return self._pages[self.category][self.page]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Не позволяет управлять чужой справкой, если её видимость изменится."""
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Это меню открыто не тобой.", ephemeral=True)
        return False

    async def select_category(
        self,
        interaction: discord.Interaction,
        category: str,
    ) -> None:
        """Переключает категорию и обновляет меню без нового сообщения."""
        if category not in self.catalog:
            await interaction.response.send_message("Раздел не найден.", ephemeral=True)
            return
        self.category = category
        self.page = 0
        self._refresh_controls()
        await interaction.response.edit_message(embed=self.embed, view=self)

    async def change_page(self, interaction: discord.Interaction, delta: int) -> None:
        """Перелистывает текущую категорию в допустимых границах."""
        last_page = len(self._pages[self.category]) - 1
        self.page = max(0, min(self.page + delta, last_page))
        self._refresh_controls()
        await interaction.response.edit_message(embed=self.embed, view=self)


class HelpCog(commands.Cog):
    """Справка по реально зарегистрированным командам Discord."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _top_level_commands(
        self,
        guild: discord.Guild | None,
    ) -> list[TopLevelCommand]:
        if guild is not None:
            guild_commands = self.bot.tree.get_commands(guild=guild)
            if guild_commands:
                return guild_commands
        return self.bot.tree.get_commands()

    @app_commands.command(name="help", description="Показать справку по командам бота")
    async def help_command(self, interaction: discord.Interaction) -> None:
        """Показывает приватный динамический каталог команд Discord."""
        catalog = build_help_catalog(self._top_level_commands(interaction.guild))
        if not catalog:
            await interaction.response.send_message(
                "Список команд пока недоступен.",
                ephemeral=True,
            )
            return
        view = HelpView(owner_id=interaction.user.id, catalog=catalog)
        await interaction.response.send_message(
            embed=view.embed,
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Подключает справку к боту."""
    await bot.add_cog(HelpCog(bot))
    logger.info("HelpCog успешно загружен.")
