"""Ког трекинга сообщений/голоса и генерации wrapped-сводок.

Сообщения считаются в [handlers/message_handler.py]; здесь живёт «умный» трекинг
голоса (зачёт времени только при реальной активности), перенос дневных данных в
помесячные, а также автоматические и ручные wrapped-посты (месячный/годовой
серверный и персональная рассылка в ЛС).
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from io import BytesIO

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import get_settings
from utils.activity.helpers import is_application
from utils.activity_data_manager import ActivityDataManager
from utils.error_handler import command_error_handler, safe_send
from utils.models import WrappedOptOut
from utils.time_utils import MOSCOW_TZ
from utils.top_reactions_data_manager import TopReactionsDataManager
from utils.user_stats_data_manager import UserStatsDataManager
from utils.wrapped.builder import (
    WrappedScope,
    build_personal_wrapped,
    build_server_wrapped,
)
from utils.wrapped.render import render_personal_card, render_server_card
from utils.wrapped.voice import member_is_active

logger = logging.getLogger("bot.cogs.user_stats")


class UserStatsTracker(commands.Cog):
    """Трекинг голосовой активности и wrapped-сводки.

    Attributes:
        bot: Экземпляр бота.
        stats_manager: Менеджер статистики сообщений/голоса.
        activity_manager: Менеджер игровой активности (для wrapped).
        reactions_manager: Менеджер лидерборда реакций (для wrapped).
        voice_sessions: Активные голосовые сессии {user_id: момент старта (UTC)}.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot: commands.Bot = bot
        self.stats_manager = UserStatsDataManager()
        self.activity_manager = ActivityDataManager()
        self.reactions_manager = TopReactionsDataManager()
        self.voice_sessions: dict[int, datetime] = {}
        self._scan_scheduled = False

        try:
            cfg = get_settings().user_stats
            self.periodic_voice_save.change_interval(seconds=cfg.voice_periodic_save)
            self.wrapped_scheduler.change_interval(
                time=time(hour=cfg.schedule.hour, minute=cfg.schedule.minute, tzinfo=MOSCOW_TZ)
            )
            self.periodic_voice_save.start()
            self.daily_transfer.start()
            self.wrapped_scheduler.start()
            logger.info("Фоновые задачи UserStatsTracker запущены.")
        except Exception as e:
            logger.error(f"Не удалось запустить задачи UserStatsTracker: {e}", exc_info=True)

    async def cog_unload(self) -> None:
        """Останавливает задачи и сохраняет накопленный голос."""
        self.periodic_voice_save.cancel()
        self.daily_transfer.cancel()
        self.wrapped_scheduler.cancel()
        try:
            await self._flush_active(restart=False)
        except Exception as e:
            logger.warning(f"Не удалось финально сохранить голос при выгрузке: {e}")
        logger.info("Ког UserStatsTracker выгружен.")

    # --- Трекинг голоса ---

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Сканирует голосовые каналы при старте, чтобы продолжить учёт активных сессий."""
        if self._scan_scheduled:
            return
        self._scan_scheduled = True
        asyncio.create_task(self._scan_voice_channels())

    async def _scan_voice_channels(self) -> None:
        await self.bot.wait_until_ready()
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild is None:
            return
        now = datetime.now(UTC)
        cfg = get_settings().user_stats
        for vc in guild.voice_channels:
            for member in vc.members:
                if member.bot or is_application(member):
                    continue
                if member_is_active(
                    member,
                    count_while_muted=cfg.count_while_muted,
                    min_humans=cfg.min_humans_in_channel,
                ):
                    self.voice_sessions.setdefault(member.id, now)
        logger.info(f"Скан голоса при старте: {len(self.voice_sessions)} активных сессий.")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Пересчитывает голосовую активность затронутых пользователей.

        Помимо самого ``member`` переоцениваем всех в каналах ``before`` и ``after`` —
        так ловим случай «остался один, когда сосед вышел» (его ивент тоже прилетает).
        """
        if member.bot or is_application(member):
            return

        now = datetime.now(UTC)
        affected: dict[int, discord.Member] = {}
        if not member.bot:
            affected[member.id] = member
        for channel in (before.channel, after.channel):
            if channel is None:
                continue
            for m in channel.members:
                if not m.bot and not is_application(m):
                    affected[m.id] = m

        for m in affected.values():
            self._reevaluate(m, now)

    def _reevaluate(self, member: discord.Member, now: datetime) -> None:
        """Открывает/закрывает сессию пользователя в зависимости от его активности."""
        cfg = get_settings().user_stats
        active = member_is_active(
            member,
            count_while_muted=cfg.count_while_muted,
            min_humans=cfg.min_humans_in_channel,
        )
        if active and member.id not in self.voice_sessions:
            self.voice_sessions[member.id] = now
        elif not active and member.id in self.voice_sessions:
            self._close_session(member.id, now)

    def _close_session(self, user_id: int, now: datetime) -> None:
        """Закрывает сессию и пишет накопленные секунды в БД (если в допустимом диапазоне)."""
        start = self.voice_sessions.pop(user_id, None)
        if start is None:
            return
        cfg = get_settings().user_stats
        elapsed = int((now - start).total_seconds())
        if cfg.voice_min_record <= elapsed < cfg.voice_max_record:
            asyncio.create_task(self.stats_manager.add_voice_seconds(user_id, elapsed))
        elif elapsed >= cfg.voice_max_record:
            logger.warning(f"Аномально длинная голосовая сессия {user_id} ({elapsed}s) — пропуск.")

    async def _flush_active(self, *, restart: bool) -> None:
        """Сбрасывает накопленное время активных сессий в БД.

        Args:
            restart: Если True, сессия остаётся открытой с новым стартом (периодический
                флаш). Если False, сессии закрываются (выгрузка кога).
        """
        if not self.voice_sessions:
            return
        now = datetime.now(UTC)
        cfg = get_settings().user_stats
        guild = self.bot.guilds[0] if self.bot.guilds else None

        for user_id, start in list(self.voice_sessions.items()):
            elapsed = int((now - start).total_seconds())
            if cfg.voice_min_record <= elapsed < cfg.voice_max_record:
                await self.stats_manager.add_voice_seconds(user_id, elapsed)
            elif elapsed >= cfg.voice_max_record:
                logger.warning(f"Аномальная сессия {user_id} ({elapsed}s) при флаше — сброс.")
                self.voice_sessions.pop(user_id, None)
                continue

            if not restart:
                self.voice_sessions.pop(user_id, None)
                continue

            member = guild.get_member(user_id) if guild else None
            still_active = member is not None and member_is_active(
                member,
                count_while_muted=cfg.count_while_muted,
                min_humans=cfg.min_humans_in_channel,
            )
            if still_active:
                self.voice_sessions[user_id] = now
            else:
                self.voice_sessions.pop(user_id, None)

    # --- Фоновые задачи ---

    @tasks.loop(seconds=300)
    async def periodic_voice_save(self) -> None:
        """Периодически сохраняет накопленное голосовое время активных сессий."""
        try:
            await self._flush_active(restart=True)
        except Exception as e:
            logger.error(f"Ошибка periodic_voice_save: {e}", exc_info=True)

    @periodic_voice_save.before_loop
    async def _before_voice_save(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=21, minute=0, tzinfo=UTC))  # 00:00 МСК
    async def daily_transfer(self) -> None:
        """В полночь по МСК флашит голос и переносит вчерашние дневные данные в помесячные."""
        try:
            await self._flush_active(restart=True)
            yesterday = (datetime.now(MOSCOW_TZ).date()) - timedelta(days=1)
            await self.stats_manager.transfer_daily_to_monthly(yesterday)
        except Exception as e:
            logger.error(f"Ошибка daily_transfer: {e}", exc_info=True)

    @daily_transfer.before_loop
    async def _before_daily_transfer(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=MOSCOW_TZ))
    async def wrapped_scheduler(self) -> None:
        """Раз в сутки проверяет дату и постит нужные wrapped-сводки."""
        cfg = get_settings().user_stats
        sched = cfg.schedule
        today = datetime.now(MOSCOW_TZ).date()
        try:
            if today.day == 1:
                prev = today.replace(day=1) - timedelta(days=1)
                await self._post_server_wrapped("monthly", prev.year, prev.month)
            if today.month == sched.yearly_month and today.day == sched.yearly_day:
                await self._post_server_wrapped("yearly", today.year, None)
            if (
                sched.personal_enabled
                and today.month == sched.personal_month
                and today.day == sched.personal_day
            ):
                await self._broadcast_personal_wrapped(today.year)
        except Exception as e:
            logger.error(f"Ошибка wrapped_scheduler: {e}", exc_info=True)

    @wrapped_scheduler.before_loop
    async def _before_wrapped(self) -> None:
        await self.bot.wait_until_ready()

    # --- Построение и отправка wrapped ---

    def _footnote(self) -> str | None:
        data_since = get_settings().user_stats.data_since
        if data_since:
            return f"PD Bot · данные собираются с {data_since}"
        return "PD Bot"

    def _name_resolver(self, guild: discord.Guild) -> Callable[[int], str]:
        def resolve(user_id: int) -> str:
            member = guild.get_member(user_id)
            return member.display_name if member else f"ID {user_id}"

        return resolve

    async def _fetch_avatar(self, user: discord.abc.User | None) -> bytes | None:
        """Загружает PNG аватара пользователя (None при ошибке)."""
        if user is None:
            return None
        try:
            url = str(user.display_avatar.replace(size=128, format="png").url)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception as e:
            logger.debug(f"Не удалось загрузить аватар {getattr(user, 'id', '?')}: {e}")
        return None

    async def _fetch_avatars(self, user_ids: list[int], guild: discord.Guild) -> dict[int, bytes]:
        """Загружает аватары для набора пользователей одной сессией."""
        result: dict[int, bytes] = {}
        members = [(uid, guild.get_member(uid)) for uid in user_ids]
        members = [(uid, m) for uid, m in members if m is not None]
        if not members:
            return result
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                for uid, member in members:
                    try:
                        url = str(member.display_avatar.replace(size=128, format="png").url)
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                result[uid] = await resp.read()
                    except Exception as e:
                        logger.debug(f"avatar fetch {uid}: {e}")
        except Exception as e:
            logger.debug(f"Ошибка сессии загрузки аватаров: {e}")
        return result

    def _report_channel(self) -> discord.TextChannel | None:
        channel_id = get_settings().channels.activity_reports
        channel = self.bot.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        logger.error(f"Канал для wrapped (ID: {channel_id}) не найден или не текстовый.")
        return None

    async def _render_server(self, scope: WrappedScope, year: int, month: int | None) -> bytes:
        cfg = get_settings().user_stats
        guild = self.bot.guilds[0] if self.bot.guilds else None
        summary = await build_server_wrapped(
            scope=scope,
            year=year,
            month=month,
            stats_mgr=self.stats_manager,
            activity_mgr=self.activity_manager,
            reactions_mgr=self.reactions_manager,
            top_limit=cfg.top_limit,
            footnote=self._footnote(),
        )
        names = self._name_resolver(guild) if guild else (lambda uid: f"ID {uid}")
        nom_ids = [n.user_id for n in summary.nominations if n.user_id is not None]
        avatars = await self._fetch_avatars(nom_ids, guild) if guild else {}
        return await asyncio.to_thread(render_server_card, summary, names, avatars)

    async def _post_server_wrapped(self, scope: WrappedScope, year: int, month: int | None) -> bool:
        channel = self._report_channel()
        if channel is None:
            return False
        png = await self._render_server(scope, year, month)
        title = "🎉 Серверный Wrapped"
        file = discord.File(BytesIO(png), filename="wrapped.png")
        await channel.send(content=title, file=file)
        logger.info(f"Опубликован серверный wrapped ({scope} {year}-{month}).")
        return True

    async def _broadcast_personal_wrapped(self, year: int) -> None:
        """Рассылает персональные карточки активным участникам в ЛС (с учётом opt-out)."""
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild is None:
            return
        cfg = get_settings().user_stats
        opted_out = set(await WrappedOptOut.all().values_list("user_id", flat=True))

        yearly = await self.stats_manager.get_yearly_totals(year)
        yearly = self.stats_manager.merge_totals(
            yearly, await self.stats_manager.get_daily_totals_by_prefix(str(year))
        )
        active_ids = [uid for uid, t in yearly.items() if t.messages > 0 or t.voice_seconds > 0]

        sent = 0
        for user_id in active_ids:
            if user_id in opted_out:
                continue
            member = guild.get_member(user_id)
            if member is None or member.bot:
                continue
            try:
                personal = await build_personal_wrapped(
                    user_id=user_id,
                    year=year,
                    stats_mgr=self.stats_manager,
                    activity_mgr=self.activity_manager,
                    reactions_mgr=self.reactions_manager,
                    footnote=self._footnote(),
                )
                avatar = await self._fetch_avatar(member)
                png = await asyncio.to_thread(
                    render_personal_card, personal, member.display_name, avatar
                )
                file = discord.File(BytesIO(png), filename="my_wrapped.png")
                await member.send(
                    content=(
                        "Твой персональный итог года на сервере! "
                        "Отписаться от рассылки — команда `/wrapped_optout`."
                    ),
                    file=file,
                )
                sent += 1
            except discord.Forbidden:
                logger.debug(f"ЛС закрыты для {user_id} — пропуск персонального wrapped.")
            except Exception as e:
                logger.error(f"Ошибка отправки персонального wrapped {user_id}: {e}")
            await asyncio.sleep(cfg.dm_send_delay)
        logger.info(f"Персональный wrapped разослан: {sent} из {len(active_ids)} активных.")

    # --- Команды ---

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="wrapped", description="[Админ] Персональный итог года (картинкой)."
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        user="Чей wrapped показать (по умолчанию — ваш).",
        year="Год (по умолчанию — текущий).",
    )
    @command_error_handler
    async def wrapped_command(
        self,
        ctx: commands.Context,
        user: discord.Member | None = None,
        year: int | None = None,
    ) -> None:
        """Собирает и отправляет персональную годовую карточку wrapped."""
        target = user or ctx.author
        target_year = year or datetime.now(MOSCOW_TZ).year
        await ctx.defer()

        personal = await build_personal_wrapped(
            user_id=target.id,
            year=target_year,
            stats_mgr=self.stats_manager,
            activity_mgr=self.activity_manager,
            reactions_mgr=self.reactions_manager,
            footnote=self._footnote(),
        )
        display_name = getattr(target, "display_name", str(target))
        avatar = await self._fetch_avatar(target)
        png = await asyncio.to_thread(render_personal_card, personal, display_name, avatar)
        file = discord.File(BytesIO(png), filename="my_wrapped.png")
        await ctx.send(file=file)

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="topstats", description="[Админ] Серверные итоги активности (картинкой)."
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(period="Период: month (текущий месяц) или year (текущий год).")
    @app_commands.choices(
        period=[
            app_commands.Choice(name="Месяц", value="month"),
            app_commands.Choice(name="Год", value="year"),
        ]
    )
    @command_error_handler
    async def topstats_command(self, ctx: commands.Context, period: str = "month") -> None:
        """Серверная wrapped-сводка за текущий месяц или год."""
        await ctx.defer()
        today = datetime.now(MOSCOW_TZ).date()
        if period == "year":
            png = await self._render_server("yearly", today.year, None)
        else:
            png = await self._render_server("monthly", today.year, today.month)
        file = discord.File(BytesIO(png), filename="topstats.png")
        await ctx.send(file=file)

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="wrapped_optout",
        description="[Админ] Включить/выключить персональную рассылку wrapped в ЛС.",
    )
    @commands.has_permissions(administrator=True)
    @command_error_handler
    async def wrapped_optout_command(self, ctx: commands.Context) -> None:
        """Переключает подписку пользователя на персональную рассылку wrapped."""
        existing = await WrappedOptOut.filter(user_id=ctx.author.id).first()
        if existing:
            await existing.delete()
            await safe_send(
                ctx, "Вы снова будете получать персональный wrapped в ЛС.", ephemeral=True
            )
        else:
            await WrappedOptOut.create(user_id=ctx.author.id)
            await safe_send(
                ctx, "Вы отписались от персональной рассылки wrapped в ЛС.", ephemeral=True
            )

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="wrapped_monthly", description="[Админ] Опубликовать месячный серверный wrapped."
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(year="Год.", month="Месяц (1-12).")
    @command_error_handler
    async def wrapped_monthly_command(self, ctx: commands.Context, year: int, month: int) -> None:
        """Ручной запуск месячного серверного wrapped."""
        if not 1 <= month <= 12:
            await safe_send(ctx, "Месяц должен быть от 1 до 12.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        ok = await self._post_server_wrapped("monthly", year, month)
        await safe_send(
            ctx,
            "Месячный wrapped опубликован." if ok else "Не удалось (проверьте канал в логах).",
            ephemeral=True,
        )

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="wrapped_yearly", description="[Админ] Опубликовать годовой серверный wrapped."
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(year="Год.")
    @command_error_handler
    async def wrapped_yearly_command(self, ctx: commands.Context, year: int) -> None:
        """Ручной запуск годового серверного wrapped."""
        await ctx.defer(ephemeral=True)
        ok = await self._post_server_wrapped("yearly", year, None)
        await safe_send(
            ctx,
            "Годовой wrapped опубликован." if ok else "Не удалось (проверьте канал в логах).",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Загружает ког UserStatsTracker в бота."""
    await bot.add_cog(UserStatsTracker(bot))
    logger.info("Ког UserStatsTracker успешно загружен.")
