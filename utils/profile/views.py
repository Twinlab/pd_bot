"""Components V2-интерфейс команды ``/profile``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Literal
from urllib.parse import quote

import discord
from discord import ButtonStyle, Interaction, ui

from config import get_settings
from utils.activity.helpers import format_time_short
from utils.channel_permissions import public_message_channel_ids
from utils.error_handler import get_incident_error_message, new_incident_id
from utils.time_utils import MOSCOW_TZ

from .builder import (
    MONTH_NAMES_RU,
    ProfileAccounts,
    ProfileMoment,
    ProfilePeriod,
    ProfileStats,
    ProfileStatsBuilder,
)

logger = logging.getLogger("bot.utils.profile_views")

ProfileTab = Literal["overview", "games", "moments", "accounts"]
ProfileMatchGame = Literal["dota", "cs"]
ProfileMatchCallback = Callable[[Interaction, discord.Member, ProfileMatchGame], Awaitable[None]]
PROFILE_TIMEOUT_SECONDS = 900
GAMES_PER_PAGE = 5
MOMENTS_LIMIT = 3

MONTH_NAMES_GENITIVE = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def _format_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _safe_text(value: str, *, limit: int = 140) -> str:
    text = " ".join(value.split())
    text = discord.utils.escape_mentions(discord.utils.escape_markdown(text))
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


class _ProfileTabs(ui.ActionRow["ProfileView"]):
    """Основные вкладки профиля."""

    def __init__(self, active: ProfileTab) -> None:
        super().__init__()
        for child in self.children:
            if isinstance(child, ui.Button):
                child.style = (
                    ButtonStyle.primary
                    if child.custom_id == f"profile_tab:{active}"
                    else ButtonStyle.secondary
                )

    @ui.button(label="Обзор", custom_id="profile_tab:overview")
    async def overview(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.show_tab(interaction, "overview")

    @ui.button(label="Игры", custom_id="profile_tab:games")
    async def games(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.show_tab(interaction, "games")

    @ui.button(label="Моменты", custom_id="profile_tab:moments")
    async def moments(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.show_tab(interaction, "moments")

    @ui.button(label="Аккаунты", custom_id="profile_tab:accounts")
    async def accounts(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.show_tab(interaction, "accounts")


class _ProfilePeriods(ui.ActionRow["ProfileView"]):
    """Быстрый выбор периода профиля."""

    def __init__(self, active: ProfilePeriod) -> None:
        super().__init__()
        selected = {
            "month": "profile_period:month",
            "year": "profile_period:year",
            "all": "profile_period:all",
        }[active.scope]
        now = datetime.now(MOSCOW_TZ)
        if active.scope == "month" and (active.year, active.month) != (now.year, now.month):
            selected = "profile_period:custom"
        for child in self.children:
            if isinstance(child, ui.Button):
                child.style = (
                    ButtonStyle.primary if child.custom_id == selected else ButtonStyle.secondary
                )

    @ui.button(label="Этот месяц", custom_id="profile_period:month")
    async def month(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.change_period(interaction, ProfilePeriod.current_month())

    @ui.button(label="Этот год", custom_id="profile_period:year")
    async def year(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.change_period(interaction, ProfilePeriod.current_year())

    @ui.button(label="Всё время", custom_id="profile_period:all")
    async def all_time(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.change_period(interaction, ProfilePeriod.all_time())

    @ui.button(label="Другой период", emoji="📅", custom_id="profile_period:custom")
    async def custom(self, interaction: Interaction, _button: ui.Button) -> None:
        await interaction.response.send_modal(ProfilePeriodModal(self.view))


class _GamesPager(ui.ActionRow["ProfileView"]):
    """Пагинация списка игр."""

    def __init__(self, *, page: int, pages: int) -> None:
        super().__init__()
        self.previous.disabled = page <= 0
        self.next.disabled = page >= pages - 1

    @ui.button(label="Назад", emoji="◀️", custom_id="profile_games:previous")
    async def previous(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.change_games_page(interaction, -1)

    @ui.button(label="Дальше", emoji="▶️", custom_id="profile_games:next")
    async def next(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.change_games_page(interaction, 1)


class _ProfileMatchActions(ui.ActionRow["ProfileView"]):
    """Быстрые действия с последними матчами владельца профиля."""

    @ui.button(label="Последний матч Dota 2", custom_id="profile_match:dota")
    async def dota(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.show_last_match(interaction, "dota")

    @ui.button(label="Последний матч CS2", custom_id="profile_match:cs")
    async def cs(self, interaction: Interaction, _button: ui.Button) -> None:
        await self.view.show_last_match(interaction, "cs")


class ProfilePeriodModal(ui.Modal, title="Выбрать период"):
    """Модалка выбора произвольного месяца."""

    def __init__(self, profile_view: ProfileView) -> None:
        super().__init__()
        self.profile_view = profile_view
        now = datetime.now(MOSCOW_TZ)
        selected_month = profile_view.period.month or now.month
        selected_year = profile_view.period.year or now.year

        self.month_select: ui.Select[ProfilePeriodModal] = ui.Select(
            custom_id="profile_period_month",
            placeholder="Месяц",
            options=[
                discord.SelectOption(
                    label=MONTH_NAMES_RU[month],
                    value=str(month),
                    default=month == selected_month,
                )
                for month in range(1, 13)
            ],
        )

        data_since = get_settings().user_stats.data_since
        try:
            first_year = date.fromisoformat(data_since).year if data_since else now.year
        except ValueError:
            first_year = now.year
        first_year = min(first_year, now.year)
        years = list(range(max(first_year, now.year - 24), now.year + 1))
        self.year_select: ui.Select[ProfilePeriodModal] = ui.Select(
            custom_id="profile_period_year",
            placeholder="Год",
            options=[
                discord.SelectOption(
                    label=str(year),
                    value=str(year),
                    default=year == selected_year,
                )
                for year in reversed(years)
            ],
        )
        self.add_item(ui.Label(text="Месяц", component=self.month_select))
        self.add_item(ui.Label(text="Год", component=self.year_select))

    async def on_submit(self, interaction: Interaction) -> None:
        period = ProfilePeriod(
            "month",
            int(self.year_select.values[0]),
            int(self.month_select.values[0]),
        )
        await self.profile_view.change_period(interaction, period)


class ProfileView(ui.LayoutView):
    """Одна интерактивная CV2-карточка со всеми разделами профиля."""

    def __init__(
        self,
        *,
        target: discord.Member,
        builder: ProfileStatsBuilder,
        stats: ProfileStats,
        eligible_user_ids: set[int],
        match_callback: ProfileMatchCallback | None = None,
    ) -> None:
        super().__init__(timeout=PROFILE_TIMEOUT_SECONDS)
        self.target = target
        self.builder = builder
        self.eligible_user_ids = eligible_user_ids
        self.match_callback = match_callback
        self.period = stats.period
        self.active_tab: ProfileTab = "overview"
        self.games_page = 0
        self.message: discord.Message | None = None
        self._stats_cache: dict[ProfilePeriod, ProfileStats] = {stats.period: stats}
        self._moments_cache: dict[ProfilePeriod, list[ProfileMoment]] = {}
        self._accounts: ProfileAccounts | None = None
        self._interaction_lock = asyncio.Lock()
        self._active_match_requests: set[int] = set()
        self._render()

    def _current_game(self) -> str | None:
        for activity in self.target.activities:
            if activity.type == discord.ActivityType.playing and activity.name:
                return activity.name
        return None

    async def _get_stats(self) -> ProfileStats:
        stats = self._stats_cache.get(self.period)
        if stats is None:
            stats = await self.builder.build_stats(
                user_id=self.target.id,
                period=self.period,
                eligible_user_ids=self.eligible_user_ids,
                current_game=self._current_game(),
            )
            self._stats_cache[self.period] = stats
        else:
            stats.current_game = self._current_game()
        return stats

    async def _get_moments(self) -> list[ProfileMoment]:
        # Права могли измениться после предыдущего открытия вкладки.
        moments = await self.builder.build_moments(
            user_id=self.target.id,
            period=self.period,
            allowed_channel_ids=public_message_channel_ids(self.target.guild),
            limit=MOMENTS_LIMIT,
        )
        self._moments_cache[self.period] = moments
        return moments

    async def _get_accounts(self) -> ProfileAccounts:
        if self._accounts is None:
            self._accounts = await self.builder.build_accounts(self.target.id)
        return self._accounts

    def _joined_label(self) -> str | None:
        if self.target.joined_at is None:
            return None
        joined = self.target.joined_at.astimezone(MOSCOW_TZ)
        return f"На сервере с {joined.day} {MONTH_NAMES_GENITIVE[joined.month]} {joined.year}"

    def _period_label(self, stats: ProfileStats | None = None) -> str:
        parts = [self.period.label]
        joined = self._joined_label()
        if joined:
            parts.append(joined)
        if self.period.scope == "all":
            data_since = (
                stats.data_since if stats is not None else get_settings().user_stats.data_since
            )
            try:
                if data_since:
                    start = date.fromisoformat(data_since)
                    parts.append(
                        f"данные с {start.day} {MONTH_NAMES_GENITIVE[start.month]} {start.year}"
                    )
            except ValueError:
                pass
        return " · ".join(parts)

    def _header(self, stats: ProfileStats | None = None) -> ui.Section:
        display_name = _safe_text(self.target.display_name, limit=80)
        if self.active_tab == "accounts":
            subtitle = self._joined_label() or "Сохранённые игровые привязки"
        else:
            subtitle = self._period_label(stats)
        return ui.Section(
            f"## Профиль {display_name}",
            subtitle,
            accessory=ui.Thumbnail(self.target.display_avatar.url),
        )

    @staticmethod
    def _rank_line(stats: ProfileStats) -> str | None:
        ranks: list[str] = []
        if stats.message_rank is not None:
            ranks.append(f"#{stats.message_rank} по сообщениям")
        if stats.voice_rank is not None:
            ranks.append(f"#{stats.voice_rank} по войсу")
        if stats.reaction_rank is not None:
            ranks.append(f"#{stats.reaction_rank} по реакциям")
        return " · ".join(ranks) if ranks else None

    def _add_overview(self, container: ui.Container, stats: ProfileStats) -> None:
        container.add_item(
            ui.TextDisplay(
                f"💬 **Сообщения:** {_format_number(stats.messages)}\n"
                f"🎙 **В голосе:** {format_time_short(stats.voice_seconds)}\n"
                f"🎮 **В играх:** {format_time_short(stats.game_seconds)}\n"
                f"❤️ **Реакции:** {_format_number(stats.reactions)}"
            )
        )
        container.add_item(ui.Separator())

        details: list[str] = []
        if stats.favorite_game is not None:
            game, seconds = stats.favorite_game
            details.append(
                f"⭐ **Любимая игра:** {_safe_text(game)} — {format_time_short(seconds)}"
            )
        else:
            details.append("⭐ **Любимая игра:** пока нет данных")
        if stats.current_game:
            details.append(f"🎮 **Сейчас играет:** {_safe_text(stats.current_game)}")
        rank_line = self._rank_line(stats)
        if rank_line:
            details.append(f"-# {rank_line}")
        container.add_item(ui.TextDisplay("\n".join(details)))

    def _add_games(self, container: ui.Container, stats: ProfileStats) -> None:
        if not stats.top_games:
            container.add_item(ui.TextDisplay("*За выбранный период игровой активности нет.*"))
            return

        pages = max(1, (len(stats.top_games) + GAMES_PER_PAGE - 1) // GAMES_PER_PAGE)
        self.games_page = min(self.games_page, pages - 1)
        start = self.games_page * GAMES_PER_PAGE
        games = stats.top_games[start : start + GAMES_PER_PAGE]
        total = stats.game_seconds
        lines = []
        for index, (game, seconds) in enumerate(games, start=start + 1):
            share = round(seconds / total * 100) if total else 0
            lines.append(
                f"{index}. **{_safe_text(game)}** — {format_time_short(seconds)} · {share}%"
            )
        lines.append(f"\n-# Всего: {format_time_short(total)}")
        if pages > 1:
            lines.append(f"-# Страница {self.games_page + 1}/{pages}")
        container.add_item(ui.TextDisplay("\n".join(lines)))
        if pages > 1:
            container.add_item(_GamesPager(page=self.games_page, pages=pages))

    @staticmethod
    def _add_moments(container: ui.Container, moments: list[ProfileMoment]) -> None:
        if not moments:
            container.add_item(ui.TextDisplay("*За выбранный период популярных сообщений нет.*"))
            return
        for index, moment in enumerate(moments, 1):
            content = _safe_text(moment.content) or "*Сообщение без текста*"
            container.add_item(
                ui.Section(
                    f"**{index}.** «{content}»\n❤️ {_format_number(moment.reactions)} реакций",
                    accessory=ui.Button(
                        style=ButtonStyle.link,
                        label="Открыть",
                        url=moment.jump_url,
                    ),
                )
            )

    @staticmethod
    def _add_accounts(container: ui.Container, accounts: ProfileAccounts) -> None:
        if accounts.dota_ids:
            dota_lines = [
                f"• [{player_id}](https://stratz.com/players/{player_id})"
                for player_id in accounts.dota_ids
            ]
            container.add_item(ui.TextDisplay("### Dota 2\n" + "\n".join(dota_lines)))
        else:
            container.add_item(
                ui.TextDisplay("### Dota 2\n*Аккаунты не привязаны — используйте `/link`.*")
            )

        container.add_item(ui.Separator())
        if accounts.faceit:
            faceit_lines = [
                f"• [{_safe_text(account.nickname, limit=80)}]"
                f"(https://www.faceit.com/en/players/{quote(account.nickname, safe='')})"
                for account in accounts.faceit
            ]
            container.add_item(ui.TextDisplay("### Counter-Strike 2\n" + "\n".join(faceit_lines)))
        else:
            container.add_item(
                ui.TextDisplay(
                    "### Counter-Strike 2\n*FACEIT не привязан — используйте `/cslink`.*"
                )
            )

    def _render(self) -> None:
        self.clear_items()
        stats = self._stats_cache.get(self.period)
        container: ui.Container = ui.Container(accent_colour=discord.Colour.blurple())
        container.add_item(self._header(stats))
        container.add_item(ui.Separator())

        if self.active_tab == "overview" and stats is not None:
            self._add_overview(container, stats)
        elif self.active_tab == "games" and stats is not None:
            self._add_games(container, stats)
        elif self.active_tab == "moments":
            self._add_moments(container, self._moments_cache.get(self.period, []))
        elif self.active_tab == "accounts":
            self._add_accounts(container, self._accounts or ProfileAccounts())

        container.add_item(ui.Separator())
        if self.match_callback is not None:
            container.add_item(_ProfileMatchActions())
            container.add_item(ui.Separator())
        container.add_item(_ProfileTabs(self.active_tab))
        if self.active_tab != "accounts":
            container.add_item(_ProfilePeriods(self.period))
        self.add_item(container)

    async def show_tab(self, interaction: Interaction, tab: ProfileTab) -> None:
        """Переключает вкладку, лениво загружая только необходимые данные."""
        await interaction.response.defer()
        async with self._interaction_lock:
            self.active_tab = tab
            self.games_page = 0
            if tab in {"overview", "games"}:
                await self._get_stats()
            elif tab == "moments":
                await self._get_moments()
            else:
                await self._get_accounts()
            self._render()
            await interaction.edit_original_response(view=self)

    async def change_period(self, interaction: Interaction, period: ProfilePeriod) -> None:
        """Меняет период и обновляет активную вкладку."""
        await interaction.response.defer()
        async with self._interaction_lock:
            self.period = period
            self.games_page = 0
            if self.active_tab in {"overview", "games"}:
                await self._get_stats()
            elif self.active_tab == "moments":
                await self._get_moments()
            self._render()
            await interaction.edit_original_response(view=self)

    async def change_games_page(self, interaction: Interaction, delta: int) -> None:
        """Перелистывает уже загруженный список игр."""
        await interaction.response.defer()
        async with self._interaction_lock:
            stats = await self._get_stats()
            pages = max(1, (len(stats.top_games) + GAMES_PER_PAGE - 1) // GAMES_PER_PAGE)
            self.games_page = max(0, min(self.games_page + delta, pages - 1))
            self._render()
            await interaction.edit_original_response(view=self)

    async def show_last_match(
        self,
        interaction: Interaction,
        game: ProfileMatchGame,
    ) -> None:
        """Отправляет приватную карточку последнего матча владельца профиля."""
        if self.match_callback is None:
            await interaction.response.send_message(
                "Просмотр матчей сейчас недоступен.",
                ephemeral=True,
            )
            return
        user_id = interaction.user.id
        if user_id in self._active_match_requests:
            await interaction.response.send_message(
                "Последний матч уже загружается.",
                ephemeral=True,
            )
            return

        self._active_match_requests.add(user_id)
        try:
            await self.match_callback(interaction, self.target, game)
        finally:
            self._active_match_requests.discard(user_id)

    async def on_timeout(self) -> None:
        """Отключает интерактивные кнопки, сохраняя внешние ссылки."""
        for child in self.walk_children():
            if isinstance(child, ui.Button) and child.style != ButtonStyle.link:
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                logger.debug("Не удалось отключить кнопки истёкшего профиля.")

    async def on_error(
        self,
        interaction: Interaction,
        error: Exception,
        item: ui.Item[ProfileView],
    ) -> None:
        """Логирует ошибку компонента и отвечает только инициатору."""
        incident_id = new_incident_id()
        logger.error(
            f"Ошибка ProfileView в компоненте {item} [{incident_id}]: {error}",
            exc_info=(type(error), error, error.__traceback__),
            extra={
                "context": {
                    "incident_id": incident_id,
                    "profile_user_id": self.target.id,
                    "interaction_user_id": interaction.user.id,
                }
            },
        )
        message = get_incident_error_message(incident_id)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
