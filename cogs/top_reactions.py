"""Ког лидерборда сообщений с наибольшим числом уникальных реакций.

Слушает события Discord (`on_raw_reaction_add/remove/clear/clear_emoji/message_delete`)
и поддерживает в БД таблицы ReactedMessage / MessageReactor. При первой реакции на
ранее неизвестное боту сообщение выполняет ленивую подгрузку: фетчит сообщение и все
существующие реакции на нём, чтобы счётчик был корректным.

Команда `/topreactions [period]` показывает топ сообщений с пагинацией кнопками.
"""

import logging
from datetime import UTC, datetime

import discord
from discord import ButtonStyle, Interaction, app_commands, ui
from discord.ext import commands

from config import get_settings
from utils.error_handler import command_error_handler
from utils.role_reaction_data_manager import RoleReactionDataManager
from utils.top_reactions_data_manager import (
    LeaderboardEntry,
    PeriodType,
    TopReactionsDataManager,
)

# Спецсимволы Discord-markdown, которые ломают рендер при попадании в превью.
# escape_markdown из discord.utils эскейпит только * _ ~ | `, скобки же
# нужно чинить руками — иначе [...] из текста схлопывается с нашим
# wrapper-ом [preview](jump_url) и парсер уезжает.
_MD_TRANSLATE = str.maketrans(
    {
        "[": r"\[",
        "]": r"\]",
        "(": r"\(",
        ")": r"\)",
        "*": r"\*",
        "_": r"\_",
        "~": r"\~",
        "`": r"\`",
        "|": r"\|",
        ">": r"\>",
        "\\": r"\\",
    }
)

logger = logging.getLogger("bot.cogs.top_reactions")


PERIOD_TITLES: dict[str, str] = {
    "month": "🔥 Топ сообщений за месяц",
    "year": "📅 Топ сообщений за год",
    "all": "🏆 Топ сообщений за всё время",
}


def _format_author(member: discord.Member | discord.User | None, author_id: int) -> str:
    """Возвращает упоминание участника или fallback с ID."""
    if member is None:
        return f"<@{author_id}>"
    return member.mention


def _format_preview(content: str, max_len: int) -> str:
    """Готовит безопасное превью сообщения для подстановки в `[preview](url)`.

    Делает три вещи:
      1. Схлопывает любые whitespace-последовательности в один пробел.
      2. Эскейпит спецсимволы markdown — особенно `[ ] ( )`, иначе вложенные
         ссылки / квадратные скобки рвут наш wrapper-ссылку и Discord начинает
         показывать сырой URL и упоминания.
      3. Обрезает до `max_len` (символов исходного текста — после эскейпа
         строка длиннее, но это нормально, лимита Discord на длину
         description обычно достаточно).
    """
    text = " ".join(content.split())
    if not text:
        return "*(вложение / без текста)*"
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text.translate(_MD_TRANSLATE)


def _build_embed(
    *,
    entries: list[LeaderboardEntry],
    page: int,
    total_pages: int,
    period: PeriodType,
    guild: discord.Guild | None,
) -> discord.Embed:
    """Формирует красивый embed для одной страницы лидерборда.

    Каждая позиция: ранг, счётчик уникальных реакторов, упоминание автора,
    кликабельный заголовок-ссылка на сообщение и превью текста.
    """
    settings = get_settings()
    title = PERIOD_TITLES.get(period, "Топ сообщений")
    embed = discord.Embed(
        title=title,
        color=settings.get_discord_color("default"),
        timestamp=datetime.now(UTC),
    )

    if not entries:
        embed.description = "*Пока нет сообщений с реакциями за этот период.*"
        return embed

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    parts: list[str] = []
    base_rank = page * settings.top_reactions.per_page
    preview_len = settings.top_reactions.preview_inline_length

    for offset, entry in enumerate(entries, start=1):
        rank = base_rank + offset
        prefix = medals.get(rank, f"`#{rank}`")

        member = guild.get_member(entry.author_id) if guild else None
        author = _format_author(member, entry.author_id)

        preview = _format_preview(entry.content, preview_len)
        hist_marker = " *(архив)*" if entry.is_historical else ""

        parts.append(
            f"{prefix} **{entry.reactor_count}** реакций{hist_marker} • {author}\n"
            f"[{preview}]({entry.jump_url})"
        )

    embed.description = "\n\n".join(parts)
    if total_pages > 1:
        embed.set_footer(text=f"Страница {page + 1} из {total_pages}")
    return embed


class TopReactionsView(ui.View):
    """View с кнопками пагинации для лидерборда."""

    def __init__(
        self,
        *,
        entries: list[LeaderboardEntry],
        period: PeriodType,
        per_page: int,
        guild: discord.Guild | None,
        invoker_id: int,
        timeout: int,
    ) -> None:
        super().__init__(timeout=timeout)
        self.entries = entries
        self.period = period
        self.per_page = per_page
        self.guild = guild
        self.invoker_id = invoker_id
        self.current_page = 0
        self.total_pages = max(1, (len(entries) + per_page - 1) // per_page)
        self.message: discord.Message | None = None
        self._update_buttons()

    def _page_entries(self) -> list[LeaderboardEntry]:
        start = self.current_page * self.per_page
        end = start + self.per_page
        return self.entries[start:end]

    def _update_buttons(self) -> None:
        for item in self.children:
            if not isinstance(item, ui.Button):
                continue
            if item.custom_id == "top_reactions_prev":
                item.disabled = self.current_page == 0
            elif item.custom_id == "top_reactions_next":
                item.disabled = self.current_page >= self.total_pages - 1

    def render_embed(self) -> discord.Embed:
        return _build_embed(
            entries=self._page_entries(),
            page=self.current_page,
            total_pages=self.total_pages,
            period=self.period,
            guild=self.guild,
        )

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Только инициатор может листать страницы."""
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "Только тот, кто вызвал команду, может листать страницы.", ephemeral=True
            )
            return False
        return True

    @ui.button(label="⬅️ Назад", style=ButtonStyle.gray, custom_id="top_reactions_prev")
    async def prev_button(self, interaction: Interaction, button: ui.Button) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.render_embed(), view=self)
        else:
            await interaction.response.defer()

    @ui.button(label="Вперёд ➡️", style=ButtonStyle.gray, custom_id="top_reactions_next")
    async def next_button(self, interaction: Interaction, button: ui.Button) -> None:
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.render_embed(), view=self)
        else:
            await interaction.response.defer()

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, (ui.Button, ui.Select)):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class TopReactionsCog(commands.Cog):
    """Слушает события реакций и показывает лидерборд."""

    cog_name = "TopReactions"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = get_settings()
        self.manager = TopReactionsDataManager(
            content_preview_length=settings.top_reactions.content_preview_length
        )
        self.role_reaction_manager = RoleReactionDataManager()

    async def _build_excluded_message_ids(self, guild: discord.Guild | None) -> set[int]:
        """Собирает чёрный список id сообщений на момент выдачи лидерборда.

        В список попадают:
          1. `top_reactions.ignored_message_ids` из YAML — ручной чёрный список.
          2. id сообщения role-реакций (если включено `ignore_role_reaction_message`
             и оно вообще существует на этом гилде).
        """
        settings = get_settings()
        excluded: set[int] = set(settings.top_reactions.ignored_message_ids)

        if settings.top_reactions.ignore_role_reaction_message and guild is not None:
            try:
                info = await self.role_reaction_manager.get_message_info(guild.id)
            except Exception as e:
                logger.warning(f"Не удалось получить id сообщения role-реакций: {e}")
                info = None
            if info is not None:
                _, role_msg_id = info
                excluded.add(role_msg_id)

        return excluded

    async def _backfill_message(self, message: discord.Message) -> None:
        """Сохраняет сообщение и все его текущие реакции в БД.

        Вызывается при первом событии реакции на ранее неизвестное сообщение —
        чтобы счётчик уникальных реакторов сразу отражал реальное состояние.
        Реакции бота игнорируются.
        """
        await self.manager.upsert_message(
            message_id=message.id,
            channel_id=message.channel.id,
            author_id=message.author.id,
            content=message.content or "",
            jump_url=message.jump_url,
            posted_at=message.created_at,
        )

        bot_id = self.bot.user.id if self.bot.user else 0

        for reaction in message.reactions:
            emoji_str = str(reaction.emoji)
            try:
                async for user in reaction.users():
                    if user.id == bot_id:
                        continue
                    await self.manager.add_reactor(
                        message_id=message.id, user_id=user.id, emoji=emoji_str
                    )
            except discord.HTTPException as e:
                logger.warning(
                    f"Не удалось получить пользователей для реакции {emoji_str} "
                    f"на сообщении {message.id}: {e}"
                )

    async def _ensure_message_known(
        self, channel_id: int, message_id: int
    ) -> discord.Message | None:
        """Гарантирует, что сообщение есть в БД. Возвращает discord.Message если был fetch, иначе None.

        Если сообщение неизвестно — фетчим его и делаем backfill всех текущих реакций.
        """
        if await self.manager.message_exists(message_id):
            return None

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None

        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return None

        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden):
            return None
        except discord.HTTPException as e:
            logger.warning(f"fetch_message {message_id} упал: {e}")
            return None

        await self._backfill_message(message)
        return message

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Регистрирует новую реакцию. Подгружает сообщение, если оно неизвестно."""
        bot_id = self.bot.user.id if self.bot.user else 0
        if payload.user_id == bot_id:
            return

        emoji_str = str(payload.emoji)

        # Если сообщение незнакомое — fetch + backfill (внутри уже добавит и эту реакцию)
        fetched = await self._ensure_message_known(payload.channel_id, payload.message_id)
        if fetched is not None:
            return

        # Сообщение уже в БД — просто добавляем реактора
        await self.manager.add_reactor(
            message_id=payload.message_id, user_id=payload.user_id, emoji=emoji_str
        )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        """Удаляет конкретную запись (user, emoji) для сообщения."""
        bot_id = self.bot.user.id if self.bot.user else 0
        if payload.user_id == bot_id:
            return

        await self.manager.remove_reactor(
            message_id=payload.message_id,
            user_id=payload.user_id,
            emoji=str(payload.emoji),
        )

    @commands.Cog.listener()
    async def on_raw_reaction_clear(self, payload: discord.RawReactionClearEvent) -> None:
        """Все реакции сброшены — чистим всех реакторов сообщения."""
        await self.manager.remove_all_reactors_for_message(payload.message_id)

    @commands.Cog.listener()
    async def on_raw_reaction_clear_emoji(
        self, payload: discord.RawReactionClearEmojiEvent
    ) -> None:
        """Все реакции конкретным эмодзи сброшены — чистим их для сообщения."""
        await self.manager.remove_emoji_for_message(payload.message_id, str(payload.emoji))

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        """Сообщение удалено — помечаем в БД (jump_url работать не будет)."""
        await self.manager.mark_deleted(payload.message_id)

    @commands.hybrid_command(
        name="topreactions",
        description="Топ сообщений с наибольшим числом реакций (тест-режим, только для админов)",
    )
    @app_commands.describe(period="Период: month (за месяц), year (за год) или all (за всё время)")
    @app_commands.choices(
        period=[
            app_commands.Choice(name="За месяц", value="month"),
            app_commands.Choice(name="За год", value="year"),
            app_commands.Choice(name="За всё время", value="all"),
        ]
    )
    @commands.has_permissions(administrator=True)
    @command_error_handler
    async def top_reactions(
        self,
        ctx: commands.Context,
        period: str = "month",
    ) -> None:
        """Показывает лидерборд сообщений по числу уникальных реакторов.

        Args:
            ctx: Контекст команды.
            period: 'month' (по умолчанию), 'year' или 'all'.
        """
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer()

        period_normalized = period.lower().strip()
        if period_normalized not in ("month", "year", "all"):
            await ctx.send("Период должен быть `month`, `year` или `all`.", ephemeral=True)
            return

        settings = get_settings()
        limit = (
            settings.top_reactions.all_time_top
            if period_normalized == "all"
            else settings.top_reactions.live_top
        )

        excluded_message_ids = await self._build_excluded_message_ids(ctx.guild)

        entries = await self.manager.get_leaderboard(
            period=period_normalized,  # type: ignore[arg-type]
            limit=limit,
            excluded_message_ids=excluded_message_ids,
        )

        if not entries:
            embed = _build_embed(
                entries=[],
                page=0,
                total_pages=1,
                period=period_normalized,  # type: ignore[arg-type]
                guild=ctx.guild,
            )
            await ctx.send(embed=embed)
            return

        view = TopReactionsView(
            entries=entries,
            period=period_normalized,  # type: ignore[arg-type]
            per_page=settings.top_reactions.per_page,
            guild=ctx.guild,
            invoker_id=ctx.author.id,
            timeout=settings.top_reactions.view_timeout,
        )
        message = await ctx.send(embed=view.render_embed(), view=view)
        view.message = message

    async def cog_unload(self) -> None:
        logger.info(f"Ког {self.__class__.__name__} выгружен.")

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Обрабатывает ошибки команд кога.

        В тест-режиме команда `/topreactions` ограничена админами; обычные
        пользователи получают понятное сообщение вместо traceback.
        """
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                "Команда сейчас в тест-режиме и доступна только администраторам сервера.",
                ephemeral=True,
            )
        elif isinstance(error, commands.CommandInvokeError):
            logger.error(f"Ошибка при выполнении команды: {error.original}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {error.original}", ephemeral=True)
        else:
            logger.error(f"Необработанная ошибка в команде: {error}", exc_info=True)
            await ctx.send(f"Произошла неизвестная ошибка: {error}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Регистрирует TopReactionsCog."""
    await bot.add_cog(TopReactionsCog(bot))
    logger.info("Ког TopReactionsCog успешно загружен.")
