"""Динамическая справка по доступным slash-командам бота."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils.error_handler import get_incident_error_message, new_incident_id

logger = logging.getLogger("bot.cogs.help")

HELP_DESCRIPTION_LIMIT = 3000

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
    "CsLastMatchCog": "Counter-Strike 2",
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

_SCENARIOS = (
    ("Профиль и матчи", "Профиль и статистика", "Статистика, игровые аккаунты и последние матчи."),
    ("Собрать компанию", "Сборы", "Создай приглашение в игру и собери состав."),
    ("Послушать музыку", "Музыка", "Добавь трек, открой очередь и управляй плеером."),
    ("Развлечься", "Развлечения", "Карточка дня, цитаты и шуточные команды."),
)

_CATEGORY_HINTS = {
    "Профиль и статистика": "Игровые аккаунты и последние матчи — во вкладках профиля.",
    "Сборы": "Заполни форму и проверь превью. Приглашения уйдут после публикации.",
    "Музыка": "Зайди в голосовой канал и добавь трек через /play. Управление — на панели плеера.",
    "Развлечения": "Добавить цитату: меню сообщения → Приложения → В цитаты. Показать: /quote.",
}


@dataclass(frozen=True, slots=True)
class HelpEntry:
    """Одна строка справочника команд."""

    name: str
    description: str
    usage: str | None = None
    restricted: bool = False
    command_id: int | None = None


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


def _owner_only(command: HelpCommand) -> bool:
    wrapped = getattr(command, "wrapped", None)
    # Узнаём штатный декоратор без выполнения проверок: среди них бывают кулдауны.
    return any(
        getattr(check, "__module__", "") == "discord.ext.commands.core"
        and getattr(check, "__qualname__", "") == "is_owner.<locals>.predicate"
        for check in getattr(wrapped, "checks", ())
    )


def _command_access(
    command: HelpCommand,
    *,
    permissions: discord.Permissions,
    is_owner: bool,
    in_guild: bool,
) -> tuple[bool, bool]:
    owner_only = _owner_only(command)
    restricted = owner_only
    if owner_only and not is_owner:
        return False, restricted
    node: HelpCommand | app_commands.Group | None = command
    while node is not None:
        if node.guild_only and not in_guild:
            return False, restricted
        required = node.default_permissions
        if required is not None:
            restricted = True
            if not permissions.administrator and (
                required.value == 0 or not permissions.is_superset(required)
            ):
                return False, restricted
        node = getattr(node, "parent", None)
    return True, restricted


def build_help_catalog(
    top_level: list[TopLevelCommand],
    *,
    permissions: discord.Permissions,
    is_owner: bool = False,
    in_guild: bool = True,
    command_ids: dict[str, int] | None = None,
) -> HelpCatalog:
    """Собирает каталог по локальным правам, не запуская проверки команд."""
    grouped: dict[str, list[HelpEntry]] = defaultdict(list)
    for command in _walk_commands(top_level):
        if isinstance(command, app_commands.Command) and command.qualified_name == "help":
            continue

        allowed, restricted = _command_access(
            command, permissions=permissions, is_owner=is_owner, in_guild=in_guild
        )
        if not allowed:
            continue
        category = _category_for(command)
        if isinstance(command, app_commands.ContextMenu):
            target = "пользователя" if command.type is discord.AppCommandType.user else "сообщения"
            entry = HelpEntry(
                name=command.name,
                description=f"Контекстное меню {target}",
                usage=f"Меню {target} → Приложения → {command.name}",
                restricted=restricted,
            )
        else:
            entry = HelpEntry(
                name=command.qualified_name,
                description=command.description.strip() or "Без описания",
                restricted=restricted,
                command_id=(command_ids or {}).get(command.qualified_name.split()[0]),
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
    usage = f"`{discord.utils.escape_mentions(entry.usage or f'/{entry.name}')}`"
    if entry.command_id is not None and entry.usage is None:
        usage = f"</{entry.name}:{entry.command_id}>"
    lock = "🔒 " if entry.restricted else ""
    return f"{lock}{usage} — {description}"


def build_help_pages(entries: tuple[HelpEntry, ...]) -> tuple[str, ...]:
    """Разбивает каталог с запасом под заголовок и подсказки Components V2."""
    page_lines: list[list[str]] = [[]]
    page_length = 0
    for entry in entries:
        line = _entry_line(entry)
        if page_lines[-1] and page_length + len(line) + 1 > HELP_DESCRIPTION_LIMIT:
            page_lines.append([])
            page_length = 0
        page_lines[-1].append(line)
        page_length += len(line) + 1

    return tuple("\n".join(lines) for lines in page_lines)


class HelpCategorySelect(discord.ui.Select["HelpView"]):
    """Переключатель разделов справки."""

    def __init__(self, catalog: HelpCatalog, selected: str | None) -> None:
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


class HelpSectionButton(discord.ui.Button["HelpView"]):
    """Переход к разделу или на главную без запуска команды."""

    def __init__(self, label: str, category: str | None) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.select_category(interaction, self.category)


class HelpView(discord.ui.LayoutView):
    """Личная CV2-справка: сценарии, каталог и закрытие истёкшего меню."""

    def __init__(self, *, owner_id: int, catalog: HelpCatalog) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.catalog = catalog
        self.category: str | None = None
        self.page = 0
        self.message: discord.Message | None = None
        self._expired = False
        self._lock = asyncio.Lock()
        self._pages = {category: build_help_pages(entries) for category, entries in catalog.items()}
        self._render()

    def _render(self) -> None:
        self.clear_items()
        container: discord.ui.Container = discord.ui.Container(
            accent_colour=discord.Colour.blurple()
        )
        if self.category is None:
            container.add_item(discord.ui.TextDisplay("## PD Bot · Чем займёмся?"))
            container.add_item(
                discord.ui.TextDisplay("Открой раздел или выбери категорию в меню ниже.")
            )
            for label, category, description in _SCENARIOS:
                if category not in self.catalog:
                    continue
                text = f"**{label}**\n{description}"
                if self._expired:
                    container.add_item(discord.ui.TextDisplay(text))
                else:
                    container.add_item(
                        discord.ui.Section(
                            text, accessory=HelpSectionButton("Открыть раздел", category)
                        )
                    )
        else:
            container.add_item(discord.ui.TextDisplay(f"## Справка · {self.category}"))
            if hint := _CATEGORY_HINTS.get(self.category):
                container.add_item(discord.ui.TextDisplay(hint))
            container.add_item(discord.ui.TextDisplay(self._pages[self.category][self.page]))
            page_count = len(self._pages[self.category])
            container.add_item(discord.ui.TextDisplay(f"-# Страница {self.page + 1}/{page_count}"))
            if not self._expired:
                navigation = discord.ui.ActionRow(HelpSectionButton("На главную", None))
                if page_count > 1:
                    navigation.add_item(HelpPageButton(-1, disabled=self.page == 0))
                    navigation.add_item(HelpPageButton(1, disabled=self.page >= page_count - 1))
                container.add_item(navigation)
        container.add_item(discord.ui.Separator())
        if self._expired:
            container.add_item(
                discord.ui.TextDisplay("Меню закрыто. Открой новую справку командой `/help`.")
            )
        else:
            container.add_item(
                discord.ui.ActionRow(HelpCategorySelect(self.catalog, self.category))
            )
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Не позволяет управлять чужой справкой, если её видимость изменится."""
        if self._expired:
            await interaction.response.send_message(
                "Меню закрыто. Открой /help заново.", ephemeral=True
            )
            return False
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Это меню открыто не тобой.", ephemeral=True)
        return False

    async def select_category(
        self,
        interaction: discord.Interaction,
        category: str | None,
    ) -> None:
        """Переключает категорию и обновляет меню без нового сообщения."""
        if category is not None and category not in self.catalog:
            await interaction.response.send_message("Раздел не найден.", ephemeral=True)
            return
        await interaction.response.defer()
        async with self._lock:
            self.category = category
            self.page = 0
            self._render()
            self.message = await interaction.edit_original_response(view=self)

    async def change_page(self, interaction: discord.Interaction, delta: int) -> None:
        """Перелистывает текущую категорию в допустимых границах."""
        await interaction.response.defer()
        async with self._lock:
            if self.category is not None:
                last_page = len(self._pages[self.category]) - 1
                self.page = max(0, min(self.page + delta, last_page))
            self._render()
            self.message = await interaction.edit_original_response(view=self)

    async def on_timeout(self) -> None:
        """Убирает устаревшие элементы управления, оставляя видимый путь назад."""
        async with self._lock:
            self._expired = True
            self._render()
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    logger.debug("Не удалось закрыть истёкшую справку.")

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        """Связывает личное сообщение об ошибке с инцидентом в журнале."""
        incident_id = new_incident_id()
        logger.error(
            "Ошибка интерфейса справки [%s]",
            incident_id,
            exc_info=(type(error), error, error.__traceback__),
            extra={"context": {"incident_id": incident_id, "user_id": interaction.user.id}},
        )
        message = get_incident_error_message(incident_id)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class HelpCog(commands.Cog):
    """Справка по реально зарегистрированным командам Discord."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._command_ids: dict[int | None, dict[str, int]] = {}
        self._retry_after: dict[int | None, float] = {}
        self._fetch_lock = asyncio.Lock()

    def _top_level_commands(
        self,
        guild: discord.Guild | None,
    ) -> list[TopLevelCommand]:
        if guild is not None:
            guild_commands = self.bot.tree.get_commands(guild=guild)
            if guild_commands:
                return guild_commands
        return self.bot.tree.get_commands()

    async def _get_command_ids(self, guild: discord.Guild | None) -> dict[str, int]:
        scope = guild.id if guild else None
        async with self._fetch_lock:
            if scope in self._command_ids:
                return self._command_ids[scope]
            if time.monotonic() < self._retry_after.get(scope, 0):
                return {}
            try:
                synced = await asyncio.wait_for(
                    self.bot.tree.fetch_commands(guild=guild), timeout=5
                )
            except (discord.HTTPException, TimeoutError):
                self._retry_after[scope] = time.monotonic() + 60
                logger.warning("Не удалось получить ссылки slash-команд для справки.")
                return {}
            result = {
                command.name: command.id
                for command in synced
                if command.type is discord.AppCommandType.chat_input
            }
            self._command_ids[scope] = result
            return result

    @app_commands.command(name="help", description="Показать справку по командам бота")
    async def help_command(self, interaction: discord.Interaction) -> None:
        """Показывает приватный динамический каталог команд Discord."""
        await interaction.response.defer(ephemeral=True)
        top_level = self._top_level_commands(interaction.guild)
        scope = (
            interaction.guild
            if interaction.guild is not None and self.bot.tree.get_commands(guild=interaction.guild)
            else None
        )
        command_ids = await self._get_command_ids(scope)
        is_owner = False
        if any(_owner_only(command) for command in _walk_commands(top_level)):
            try:
                is_owner = await self.bot.is_owner(interaction.user)
            except discord.HTTPException:
                logger.warning("Не удалось проверить владельца для справки.")
        catalog = build_help_catalog(
            top_level,
            permissions=interaction.permissions,
            is_owner=is_owner,
            in_guild=interaction.guild is not None,
            command_ids=command_ids,
        )
        if not catalog:
            await interaction.followup.send(
                "Список команд пока недоступен.",
                ephemeral=True,
            )
            return
        view = HelpView(owner_id=interaction.user.id, catalog=catalog)
        view.message = await interaction.followup.send(
            view=view,
            ephemeral=True,
            wait=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    """Подключает справку к боту."""
    await bot.add_cog(HelpCog(bot))
    logger.info("HelpCog успешно загружен.")
