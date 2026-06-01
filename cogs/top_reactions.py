"""Ког лидерборда сообщений с наибольшим числом уникальных реакций.

Слушает события Discord (`on_raw_reaction_add/remove/clear/clear_emoji/message_delete`)
и поддерживает в БД таблицы ReactedMessage / MessageReactor. При первой реакции на
ранее неизвестное боту сообщение выполняет ленивую подгрузку: фетчит сообщение и все
существующие реакции на нём, чтобы счётчик был корректным.

Команда `/topreactions` показывает топ сообщений (или авторов) с пагинацией.
Также раз в месяц публикует автоматический отчёт за прошлый месяц в канал
``channels.activity_reports`` (1-го числа в 12:00 МСК — то же время, что и
ежемесячный отчёт ActivityTracker).
"""

import logging
from datetime import UTC, datetime, time

import discord
from discord import ButtonStyle, Interaction, app_commands, ui
from discord.ext import commands, tasks

from config import get_settings
from utils.error_handler import command_error_handler
from utils.role_reaction_data_manager import RoleReactionDataManager
from utils.time_utils import MOSCOW_TZ
from utils.top_reactions_data_manager import (
    AuthorLeaderboardEntry,
    LeaderboardEntry,
    PeriodType,
    TopReactionsDataManager,
)

RU_MONTHS: dict[int, str] = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}

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


def _period_label(period: PeriodType, *, year: int | None = None, month: int | None = None) -> str:
    """Краткое описание выбранного периода для заголовка embed."""
    if year is not None and month is not None:
        return f"{RU_MONTHS.get(month, str(month))} {year}"
    if year is not None:
        return f"{year}"
    if month is not None:
        return f"{RU_MONTHS.get(month, str(month))}"
    if period == "month":
        return "месяц"
    if period == "year":
        return "год"
    return "всё время"


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
    year: int | None = None,
    month: int | None = None,
) -> discord.Embed:
    """Формирует красивый embed для одной страницы лидерборда сообщений.

    Каждая позиция: ранг, счётчик уникальных реакторов, упоминание автора,
    кликабельный заголовок-ссылка на сообщение и превью текста.
    """
    settings = get_settings()
    title = f"🏆 Топ сообщений · {_period_label(period, year=year, month=month)}"
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


def _build_authors_embed(
    *,
    entries: list[AuthorLeaderboardEntry],
    page: int,
    total_pages: int,
    period: PeriodType,
    guild: discord.Guild | None,
    year: int | None = None,
    month: int | None = None,
) -> discord.Embed:
    """Embed для одной страницы лидерборда авторов.

    Каждая позиция: ранг, упоминание автора, суммарное число реакций по всем
    его сообщениям и количество сообщений, попавших в сумму.
    """
    settings = get_settings()
    title = f"👑 Топ авторов · {_period_label(period, year=year, month=month)}"
    embed = discord.Embed(
        title=title,
        color=settings.get_discord_color("default"),
        timestamp=datetime.now(UTC),
    )

    if not entries:
        embed.description = "*Пока нет авторов с реакциями за этот период.*"
        return embed

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    parts: list[str] = []
    base_rank = page * settings.top_reactions.per_page

    for offset, entry in enumerate(entries, start=1):
        rank = base_rank + offset
        prefix = medals.get(rank, f"`#{rank}`")

        member = guild.get_member(entry.author_id) if guild else None
        author = _format_author(member, entry.author_id)

        parts.append(
            f"{prefix} {author} — **{entry.total_reactions}** реакций "
            f"за {entry.message_count} сообщ."
        )

    embed.description = "\n".join(parts)
    if total_pages > 1:
        embed.set_footer(text=f"Страница {page + 1} из {total_pages}")
    return embed


class TopReactionsView(ui.View):
    """View с кнопками пагинации для лидерборда сообщений или авторов.

    Один универсальный класс — отрисовка зависит от типа элементов в
    ``entries`` (LeaderboardEntry → embed сообщений, AuthorLeaderboardEntry →
    embed авторов).
    """

    def __init__(
        self,
        *,
        entries: list[LeaderboardEntry] | list[AuthorLeaderboardEntry],
        period: PeriodType,
        per_page: int,
        guild: discord.Guild | None,
        invoker_id: int,
        timeout: int,
        year: int | None = None,
        month: int | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self.entries = entries
        self.period = period
        self.per_page = per_page
        self.guild = guild
        self.invoker_id = invoker_id
        self.year = year
        self.month = month
        self.current_page = 0
        self.total_pages = max(1, (len(entries) + per_page - 1) // per_page)
        self.message: discord.Message | None = None
        self._update_buttons()

    def _page_entries(
        self,
    ) -> list[LeaderboardEntry] | list[AuthorLeaderboardEntry]:
        start = self.current_page * self.per_page
        end = start + self.per_page
        return self.entries[start:end]  # type: ignore[return-value]

    def _update_buttons(self) -> None:
        for item in self.children:
            if not isinstance(item, ui.Button):
                continue
            if item.custom_id == "top_reactions_prev":
                item.disabled = self.current_page == 0
            elif item.custom_id == "top_reactions_next":
                item.disabled = self.current_page >= self.total_pages - 1

    def render_embed(self) -> discord.Embed:
        page_entries = self._page_entries()
        if page_entries and isinstance(page_entries[0], AuthorLeaderboardEntry):
            return _build_authors_embed(
                entries=page_entries,  # type: ignore[arg-type]
                page=self.current_page,
                total_pages=self.total_pages,
                period=self.period,
                guild=self.guild,
                year=self.year,
                month=self.month,
            )
        return _build_embed(
            entries=page_entries,  # type: ignore[arg-type]
            page=self.current_page,
            total_pages=self.total_pages,
            period=self.period,
            guild=self.guild,
            year=self.year,
            month=self.month,
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
        # Стартуем фоновую таску ежемесячного отчёта.
        # Если что-то пойдёт не так на старте — не валим ког.
        try:
            self.monthly_report.start()
            logger.info("TopReactions monthly_report фоновая задача запущена.")
        except RuntimeError as e:
            logger.warning(f"Не удалось запустить monthly_report: {e}")

    async def cog_unload(self) -> None:
        try:
            self.monthly_report.cancel()
        except Exception as e:
            logger.warning(f"Ошибка при остановке monthly_report: {e}")
        logger.info(f"Ког {self.__class__.__name__} выгружен.")

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
        reactors: list[tuple[int, str]] = []

        for reaction in message.reactions:
            emoji_str = str(reaction.emoji)
            try:
                async for user in reaction.users():
                    if user.id == bot_id:
                        continue
                    reactors.append((user.id, emoji_str))
            except discord.HTTPException as e:
                logger.warning(
                    f"Не удалось получить пользователей для реакции {emoji_str} "
                    f"на сообщении {message.id}: {e}"
                )

        # Один bulk-insert вместо одной INSERT-транзакции на каждого реактора.
        if reactors:
            await self.manager.add_reactors_bulk(message_id=message.id, reactors=reactors)

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

    def _resolve_query_params(
        self, *, month: int | None, year: int | None, all_time: bool
    ) -> tuple[PeriodType, int | None, int | None, int]:
        """Сводит (month, year, all_time) к (period, year, month, limit).

        Логика как в /mystats: явные year/month имеют приоритет; all_time
        переопределяет всё и берёт расширенный лимит ``all_time_top``.
        """
        settings = get_settings()
        if all_time:
            return "all", None, None, settings.top_reactions.all_time_top
        # period="month" — placeholder; resolve_period_range сам учтёт явные
        # year/month, а если их нет — возьмёт текущий месяц.
        return "month", year, month, settings.top_reactions.live_top

    async def _validate_period_args(
        self, ctx: commands.Context, *, month: int | None, year: int | None
    ) -> bool:
        """Возвращает True, если аргументы валидны. Иначе шлёт ошибку и False."""
        if month is not None and not (1 <= month <= 12):
            await ctx.send("Месяц должен быть от 1 до 12.", ephemeral=True)
            return False
        if year is not None and not (2000 <= year <= 2100):
            await ctx.send("Год должен быть в диапазоне 2000–2100.", ephemeral=True)
            return False
        return True

    async def _send_leaderboard(
        self,
        ctx: commands.Context,
        *,
        entries: list[LeaderboardEntry] | list[AuthorLeaderboardEntry],
        period_kind: PeriodType,
        year_arg: int | None,
        month_arg: int | None,
        empty_embed_factory: object,
    ) -> None:
        """Общий путь отправки: пустая выдача → один embed, иначе — View с пагинацией."""
        settings = get_settings()
        if not entries:
            embed = empty_embed_factory(  # type: ignore[operator]
                entries=[],
                page=0,
                total_pages=1,
                period=period_kind,
                guild=ctx.guild,
                year=year_arg,
                month=month_arg,
            )
            await ctx.send(embed=embed)
            return

        view = TopReactionsView(
            entries=entries,
            period=period_kind,
            per_page=settings.top_reactions.per_page,
            guild=ctx.guild,
            invoker_id=ctx.author.id,
            timeout=settings.top_reactions.view_timeout,
            year=year_arg,
            month=month_arg,
        )
        message = await ctx.send(embed=view.render_embed(), view=view)
        view.message = message

    @commands.hybrid_command(
        name="topreactions",
        description="Топ сообщений по числу уникальных реакторов (тест-режим, только для админов)",
    )
    @app_commands.describe(
        month="Месяц 1–12. Без значения — текущий (если не выбран all_time)",
        year="Год (например, 2025). Без значения — текущий",
        all_time="Показать топ за всё время (игнорирует month/year)",
    )
    @commands.has_permissions(administrator=True)
    @command_error_handler
    async def top_reactions(
        self,
        ctx: commands.Context,
        month: int | None = None,
        year: int | None = None,
        all_time: bool = False,
    ) -> None:
        """Показывает лидерборд сообщений по числу уникальных реакторов.

        Логика выбора периода такая же, как в /mystats:
            * без аргументов → текущий месяц;
            * только ``month`` → этот месяц текущего года;
            * только ``year`` → весь указанный год;
            * ``month`` + ``year`` → конкретный месяц;
            * ``all_time=True`` → за всё время (поверх month/year).
        """
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer()

        if not await self._validate_period_args(ctx, month=month, year=year):
            return

        period_kind, year_arg, month_arg, limit = self._resolve_query_params(
            month=month, year=year, all_time=all_time
        )
        excluded_message_ids = await self._build_excluded_message_ids(ctx.guild)

        entries = await self.manager.get_leaderboard(
            period=period_kind,
            limit=limit,
            year=year_arg,
            month=month_arg,
            excluded_message_ids=excluded_message_ids,
            ignore_self_reactions=get_settings().top_reactions.ignore_self_reactions,
        )
        await self._send_leaderboard(
            ctx,
            entries=entries,
            period_kind=period_kind,
            year_arg=year_arg,
            month_arg=month_arg,
            empty_embed_factory=_build_embed,
        )

    @commands.hybrid_command(
        name="topauthors",
        description="Топ авторов по сумме реакций на их сообщения (тест-режим, только для админов)",
    )
    @app_commands.describe(
        month="Месяц 1–12. Без значения — текущий (если не выбран all_time)",
        year="Год (например, 2025). Без значения — текущий",
        all_time="Показать топ за всё время (игнорирует month/year)",
    )
    @commands.has_permissions(administrator=True)
    @command_error_handler
    async def top_authors(
        self,
        ctx: commands.Context,
        month: int | None = None,
        year: int | None = None,
        all_time: bool = False,
    ) -> None:
        """Показывает лидерборд авторов по суммарным уникальным реакторам.

        Метрика — сумма уникальных реакторов по всем сообщениям автора
        в выбранном диапазоне (см. ``TopReactionsDataManager.get_top_authors``).
        Период разбирается так же, как у /topreactions.
        """
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer()

        if not await self._validate_period_args(ctx, month=month, year=year):
            return

        period_kind, year_arg, month_arg, limit = self._resolve_query_params(
            month=month, year=year, all_time=all_time
        )
        excluded_message_ids = await self._build_excluded_message_ids(ctx.guild)

        entries = await self.manager.get_top_authors(
            period=period_kind,
            limit=limit,
            year=year_arg,
            month=month_arg,
            excluded_message_ids=excluded_message_ids,
            ignore_self_reactions=get_settings().top_reactions.ignore_self_reactions,
        )
        await self._send_leaderboard(
            ctx,
            entries=entries,
            period_kind=period_kind,
            year_arg=year_arg,
            month_arg=month_arg,
            empty_embed_factory=_build_authors_embed,
        )

    @tasks.loop(time=time(hour=9, minute=1, tzinfo=UTC))  # 12:01 МСК (после отчёта по играм)
    async def monthly_report(self) -> None:
        """Фоновая задача: 1-го числа в 12:01 МСК шлёт топ за прошлый месяц.

        ``tasks.loop(time=...)`` срабатывает каждый день в указанное время —
        фильтр по 1-му числу делаем сами, по аналогии с ActivityTracker.
        """
        try:
            today = datetime.now(MOSCOW_TZ).date()
            if today.day != 1:
                logger.debug(f"monthly_report: сегодня {today.isoformat()} (не 1-е), пропускаем.")
                return

            if today.month == 1:
                prev_year, prev_month = today.year - 1, 12
            else:
                prev_year, prev_month = today.year, today.month - 1

            logger.info(
                f"monthly_report: запуск автоматического отчёта за {prev_year}-{prev_month:02d}."
            )
            await self._send_monthly_top_messages_report(prev_year, prev_month)
        except Exception as e:
            logger.error(f"monthly_report: критическая ошибка: {e}", exc_info=True)

    @monthly_report.before_loop
    async def before_monthly_report(self) -> None:
        try:
            await self.bot.wait_until_ready()
            logger.info("Задача TopReactions monthly_report готова к запуску.")
        except Exception as e:
            logger.error(f"before_monthly_report: {e}", exc_info=True)

    async def _send_monthly_top_messages_report(self, year: int, month: int) -> bool:
        """Собирает и публикует embed с топом сообщений за конкретный месяц.

        Отправляется в канал ``channels.activity_reports``. Возвращает True при
        успешной отправке. Если канал не найден или данных нет — пишет в лог
        и возвращает False (без падения).
        """
        settings = get_settings()
        channel_id = settings.channels.activity_reports
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                logger.error(f"monthly_report: канал {channel_id} недоступен: {e}")
                return False

        if not isinstance(channel, discord.TextChannel):
            logger.error(f"monthly_report: канал {channel_id} не TextChannel, отчёт не отправлен.")
            return False

        # Гилд берём из канала — без обхода bot.guilds (single-guild design).
        guild = channel.guild
        excluded = await self._build_excluded_message_ids(guild)

        entries = await self.manager.get_leaderboard(
            period="month",
            limit=settings.top_reactions.live_top,
            year=year,
            month=month,
            excluded_message_ids=excluded,
            ignore_self_reactions=settings.top_reactions.ignore_self_reactions,
        )

        if not entries:
            logger.info(
                f"monthly_report: за {year}-{month:02d} нет сообщений с реакциями, "
                "отчёт не отправлен."
            )
            return False

        per_page = settings.top_reactions.per_page
        total_pages = max(1, (len(entries) + per_page - 1) // per_page)
        embed = _build_embed(
            entries=entries[:per_page],
            page=0,
            total_pages=total_pages,
            period="month",
            guild=guild,
            year=year,
            month=month,
        )

        try:
            await channel.send(
                content=f"📊 Ежемесячный отчёт по реакциям за "
                f"**{RU_MONTHS.get(month, str(month))} {year}**",
                embed=embed,
            )
        except discord.HTTPException as e:
            logger.error(f"monthly_report: не удалось отправить отчёт: {e}")
            return False

        logger.info(
            f"monthly_report: отчёт за {year}-{month:02d} опубликован (позиций: {len(entries)})."
        )
        return True

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Обрабатывает MissingPermissions с понятным «тест-режим» сообщением.

        Всё остальное отдаём глобальному обработчику в ``handlers/events.py``.
        """
        if isinstance(error, commands.MissingPermissions):
            from utils.error_handler import safe_send_error

            await safe_send_error(
                ctx,
                "Команда сейчас в тест-режиме и доступна только администраторам сервера.",
            )
            return
        # Пробрасываем дальше — поднимется в Bot.on_command_error → handlers/events.py.
        raise error


async def setup(bot: commands.Bot) -> None:
    """Регистрирует TopReactionsCog."""
    await bot.add_cog(TopReactionsCog(bot))
    logger.info("Ког TopReactionsCog успешно загружен.")
