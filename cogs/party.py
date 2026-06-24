"""Ког сбора пати в игры через DM-кнопки.

Команда ``/party`` показывает инициатору эфемерное превью embed-а с кнопками
**Опубликовать** / **Отмена**; после публикации создаётся публичный embed в
канале и рассылаются DM каждому участнику с указанной серверной ролью.
В DM есть две кнопки: **Готов** и **Не готов**. Нажатие любой кнопки обновляет
embed синхронно во всех личках и в публичном канале. К сбору можно приложить
картинку (параметр ``image``).

Когда основа набирается, стартует фаза **чека готовности**: каждый из основы
должен ещё раз нажать **Подтверждаю** в течение окна; кто не успел — выбывает,
его слот занимает первый из начинки (ему прилетает DM-нудж). По завершении
бот пингует подтвердивших; если состав так и не собрался полностью —
закрывает частичным составом, а при пустом — сообщением «никого не собрали».

Админ-команды ``/party_block``, ``/party_unblock``, ``/party_blocklist``
управляют чёрным списком пользователей, которым запрещено вызывать ``/party``.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from config import get_settings
from utils.error_handler import command_error_handler, safe_send, safe_send_error
from utils.party.data_manager import PartyDataManager
from utils.party.duration import parse_minutes
from utils.party.embeds import build_party_embed
from utils.party.manager import Party, PartyManager, PartyPhase
from utils.party.views import PartyConfirmView, PartyPreviewView, PartyView
from utils.role_reaction_data_manager import RoleReactionDataManager


def _party_cooldown(ctx: commands.Context) -> commands.Cooldown:
    """Берёт текущий лимит кулдауна из настроек на каждый вызов команды."""
    return commands.Cooldown(1, get_settings().party.command_cooldown_seconds)


logger = logging.getLogger("bot.cogs.party")


class PartyCog(commands.Cog):
    """Сбор пати: команды + кнопки в DM + таймеры финализации."""

    bot: commands.Bot
    manager: PartyManager
    data_manager: PartyDataManager
    role_reaction_manager: RoleReactionDataManager
    _timers: dict[str, asyncio.Task[None]]
    _check_timers: dict[str, asyncio.Task[None]]

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = PartyManager()
        self.data_manager = PartyDataManager()
        self.role_reaction_manager = RoleReactionDataManager()
        self._timers = {}
        self._check_timers = {}

    async def _allowed_role_ids(self, guild_id: int) -> set[int]:
        """ID ролей, разрешённых для сбора (только выданные через /role_assign).

        Системная запись с ``role_id == 0`` отфильтровывается — это маркер
        самого role-message, не настоящая роль.
        """
        rows = await self.role_reaction_manager.get_all_role_reactions(guild_id)
        return {row["role_id"] for row in rows if row["role_id"] != 0}

    async def cog_unload(self) -> None:
        """Отменяет все запущенные таймеры финализации и чека готовности."""
        for task in (*self._timers.values(), *self._check_timers.values()):
            task.cancel()
        self._timers.clear()
        self._check_timers.clear()
        logger.info(f"Ког {self.__class__.__name__} выгружен.")

    def _member_resolver(
        self, guild: discord.Guild | None
    ) -> Callable[[int], discord.Member | discord.User | None]:
        """Создаёт resolver `user_id -> Member | User | None` для embed-builder."""

        def resolve(user_id: int) -> discord.Member | discord.User | None:
            if guild is not None:
                member = guild.get_member(user_id)
                if member is not None:
                    return member
            return self.bot.get_user(user_id)

        return resolve

    def _build_embed(self, party: Party, *, finalized: bool | None = None) -> discord.Embed:
        """Готовит embed для конкретного состояния пати."""
        settings = get_settings()
        guild = self.bot.get_guild(party.guild_id)
        role = guild.get_role(party.role_id) if guild else None
        initiator = self._member_resolver(guild)(party.initiator_id)
        jump_url = (
            f"https://discord.com/channels/{party.guild_id}/{party.channel_id}"
            f"/{party.public_message_id}"
        )
        return build_party_embed(
            party,
            role_name=role.name if role else f"роль #{party.role_id}",
            initiator=initiator,
            member_resolver=self._member_resolver(guild),
            initiator_emoji=settings.party.initiator_emoji,
            finalized=party.finalized if finalized is None else finalized,
            jump_url=jump_url,
        )

    async def _refresh_public_embed(self, party: Party) -> None:
        """Перерисовывает публичный embed; поглощает Discord-ошибки."""
        guild = self.bot.get_guild(party.guild_id)
        channel = self.bot.get_channel(party.channel_id) if guild else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return
        try:
            message = await channel.fetch_message(party.public_message_id)
        except (discord.NotFound, discord.Forbidden):
            return
        except discord.HTTPException as e:
            logger.warning(f"fetch_message {party.public_message_id} упал: {e}")
            return

        embed = self._build_embed(party)
        try:
            await message.edit(embed=embed)
        except (discord.NotFound, discord.Forbidden):
            pass
        except discord.HTTPException as e:
            logger.warning(f"Не удалось обновить публичный embed пати {party.id}: {e}")

    async def _refresh_dm_embeds(self, party: Party) -> None:
        """Перерисовывает embed во всех DM-сообщениях пати параллельно."""
        if not party.dm_messages:
            return
        embed = self._build_embed(party)

        async def edit_one(uid: int, msg: discord.Message) -> None:
            try:
                await msg.edit(embed=embed)
            except (discord.NotFound, discord.Forbidden):
                pass
            except discord.HTTPException as e:
                logger.warning(f"DM edit для юзера {uid} упал: {e}")

        await asyncio.gather(
            *(edit_one(uid, msg) for uid, msg in party.dm_messages.items()),
            return_exceptions=True,
        )

    async def _refresh_all_embeds(self, party: Party) -> None:
        """Обновляет публичный embed + все DM-embed синхронно."""
        await asyncio.gather(
            self._refresh_public_embed(party),
            self._refresh_dm_embeds(party),
            return_exceptions=True,
        )

    async def _send_dms(
        self,
        party: Party,
        role: discord.Role,
        initiator: discord.Member,
    ) -> int:
        """Рассылает DM с embed + кнопками. Возвращает число доставленных писем."""
        settings = get_settings()
        delivered = 0
        embed = self._build_embed(party)
        for member in role.members:
            if member.bot or member.id == initiator.id:
                continue
            if await self.data_manager.is_blocked(member.id):
                continue
            try:
                view = PartyView(cog=self, party=party)
                msg = await member.send(embed=embed, view=view)
                party.dm_messages[member.id] = msg
                delivered += 1
            except discord.Forbidden:
                logger.info(f"Юзер {member.id} закрыл DM — пропускаем")
            except discord.HTTPException as e:
                logger.warning(f"Ошибка отправки DM юзеру {member.id}: {e}")
            await asyncio.sleep(settings.party.dm_send_delay)
        return delivered

    async def _disable_dm_buttons(self, party: Party) -> None:
        """Снимает кнопки во всех DM (заменяет view на пустую)."""
        if not party.dm_messages:
            return
        embed = self._build_embed(party, finalized=True)

        async def disable_one(uid: int, msg: discord.Message) -> None:
            try:
                await msg.edit(embed=embed, view=None)
            except (discord.NotFound, discord.Forbidden):
                pass
            except discord.HTTPException as e:
                logger.warning(f"Не удалось снять кнопки в DM юзера {uid}: {e}")

        await asyncio.gather(
            *(disable_one(uid, msg) for uid, msg in party.dm_messages.items()),
            return_exceptions=True,
        )

    def _dm_view_for(self, party: Party, user_id: int) -> discord.ui.View | None:
        """Подбирает DM-view под фазу/роль юзера.

        В чеке: подтвердившим — без кнопок, ожидающим подтверждения —
        «Подтверждаю», остальным (резерв) — обычные «Готов» / «Не готов».
        """
        if party.phase is PartyPhase.READY_CHECK:
            if user_id in party.confirmed:
                return None
            if party.is_candidate(user_id):
                return PartyConfirmView(cog=self, party=party)
        return PartyView(cog=self, party=party)

    async def _sync_check_views(self, party: Party) -> None:
        """Перерисовывает все DM с embed и корректным для каждого юзера view."""
        if not party.dm_messages:
            return
        embed = self._build_embed(party)

        async def edit_one(uid: int, msg: discord.Message) -> None:
            try:
                await msg.edit(embed=embed, view=self._dm_view_for(party, uid))
            except (discord.NotFound, discord.Forbidden):
                pass
            except discord.HTTPException as e:
                logger.warning(f"Не удалось обновить DM юзера {uid} в чеке: {e}")

        await asyncio.gather(
            *(edit_one(uid, msg) for uid, msg in party.dm_messages.items()),
            return_exceptions=True,
        )

    async def _nudge_user(self, party: Party, user_id: int) -> None:
        """Шлёт в DM короткий пинг тому, кого подняли из начинки в основу."""
        msg = party.dm_messages.get(user_id)
        if msg is None:
            return
        try:
            await msg.channel.send(get_settings().party.confirm_nudge_message)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.info(f"Не удалось пнуть юзера {user_id} в чеке: {e}")

    async def _maybe_start_ready_check(self, party: Party) -> None:
        """Запускает чек готовности, когда основа набралась (если включён)."""
        settings = get_settings()
        if not settings.party.enable_ready_check:
            return
        window = timedelta(seconds=settings.party.confirm_window_seconds)
        started = await self.manager.start_ready_check(
            party.id, now=datetime.now(UTC), window=window
        )
        if started is None:
            return

        await self._sync_check_views(started)
        await self._refresh_public_embed(started)
        self._start_check_loop(started)
        logger.info(f"Пати {party.id}: основа набрана, запущен чек готовности")

    def _start_check_loop(self, party: Party) -> None:
        """Создаёт фоновый sweep-таск опроса дедлайнов подтверждения."""
        task = asyncio.create_task(self._ready_check_loop(party), name=f"party-check-{party.id}")
        self._check_timers[party.id] = task

    async def _ready_check_loop(self, party: Party) -> None:
        """Опрашивает дедлайны подтверждения, поднимает начинку, закрывает сбор."""
        settings = get_settings()
        poll = settings.party.ready_check_poll_seconds
        window = timedelta(seconds=settings.party.confirm_window_seconds)
        try:
            while True:
                await asyncio.sleep(poll)
                if self.manager.get(party.id) is None:
                    return
                tick = await self.manager.tick_ready_check(
                    party.id, now=datetime.now(UTC), window=window
                )
                if tick.finished in ("success", "partial"):
                    await self._finalize(party)
                    return
                if tick.changed:
                    for uid in tick.promoted:
                        await self._nudge_user(party, uid)
                    await self._sync_check_views(party)
                    await self._refresh_public_embed(party)
        except asyncio.CancelledError:
            return

    async def _after_confirm(self, party: Party) -> None:
        """Реакция на нажатие «Подтверждаю»: перерисовка и финал при полном составе."""
        await self._sync_check_views(party)
        await self._refresh_public_embed(party)
        if len(party.confirmed) >= party.count:
            await self._finalize(party)

    async def _finalize_after(self, party: Party, seconds: float) -> None:
        """Таймер закрытия пати. Отменяется через `task.cancel()` в `cog_unload`."""
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        await self._finalize(party)

    async def _finalize(self, party: Party) -> None:
        """Финализирует пати: пингует готовых, обновляет embed, чистит state."""
        if party.finalized:
            return
        settings = get_settings()
        guild = self.bot.get_guild(party.guild_id)
        channel = self.bot.get_channel(party.channel_id) if guild else None
        role = guild.get_role(party.role_id) if guild else None

        # cancel() атомарно помечает финализированным и удаляет из активных —
        # снимок ростера берём только после него, чтобы поздний клик не потерялся.
        cancelled = await self.manager.cancel(party.id)
        if cancelled is None:
            # Уже финализировано параллельным /party_cancel — отдаём раунд.
            return

        # Имя роли, а не mention — иначе в финальном сообщении она выглядит как кликабельный
        # пинг (даже с allowed_mentions roles=False это всё равно подсвечивается и раздражает).
        role_name = role.name if role else f"роль #{party.role_id}"

        # Если был чек готовности — пингуем только подтвердивших (полный состав или
        # частичный). Иначе работает старая логика по списку «Готовы».
        if cancelled.ready_check_started:
            roster = list(cancelled.confirmed)
            ready_pings = " ".join(f"<@{uid}>" for uid in roster)
            if not roster:
                text = settings.party.empty_finished_message.format(
                    role=role_name, comment=cancelled.comment
                )
            elif len(roster) >= cancelled.count:
                text = settings.party.finished_message_template.format(
                    ready_pings=ready_pings, role=role_name, comment=cancelled.comment
                )
            else:
                text = settings.party.partial_finished_message.format(
                    ready_pings=ready_pings, role=role_name, comment=cancelled.comment
                )
        else:
            roster = list(cancelled.ready)
            if len(roster) >= cancelled.count:
                ready_pings = " ".join(f"<@{uid}>" for uid in roster)
                text = settings.party.finished_message_template.format(
                    ready_pings=ready_pings, role=role_name, comment=cancelled.comment
                )
            else:
                text = settings.party.empty_finished_message.format(
                    role=role_name, comment=cancelled.comment
                )

        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            try:
                await channel.send(
                    text,
                    allowed_mentions=discord.AllowedMentions(
                        users=True, roles=False, everyone=False
                    ),
                )
            except discord.HTTPException as e:
                logger.warning(f"Не удалось отправить финальное сообщение пати {party.id}: {e}")

        # Сначала снимаем кнопки в DM (с серым embed-ом), потом обновляем публичный.
        await self._disable_dm_buttons(cancelled)
        await self._refresh_public_embed(cancelled)
        self._timers.pop(party.id, None)
        check_task = self._check_timers.pop(party.id, None)
        # Отменяем sweep, только если финал пришёл не из него самого.
        if check_task is not None and check_task is not asyncio.current_task():
            check_task.cancel()

    @commands.hybrid_command(
        name="party",
        description="Собрать пати в игру: разошлёт DM всем с этой ролью.",
    )
    @app_commands.describe(
        role="Игровая роль (только из /role_assign)",
        when="Через сколько закроется сбор (минут, максимум 240)",
        count="Сколько человек нужно в состав пати (включая тебя)",
        comment="Комментарий, который увидят все",
        image="Картинка к сбору (опционально)",
    )
    @commands.dynamic_cooldown(_party_cooldown, commands.BucketType.user)
    @command_error_handler
    async def party(
        self,
        ctx: commands.Context,
        role: discord.Role,
        when: app_commands.Range[int, 1, 240],
        count: app_commands.Range[int, 1, 25],
        comment: str,
        image: discord.Attachment | None = None,
    ) -> None:
        """Создаёт сбор пати. Подробности — в docstring модуля."""
        settings = get_settings()

        if ctx.guild is None:
            await safe_send_error(ctx, "чел ты долбоёб? пиши команду в конфе")
            return

        if await self.data_manager.is_blocked(ctx.author.id):
            await safe_send_error(ctx, "ты в бане")
            return

        allowed_role_ids = await self._allowed_role_ids(ctx.guild.id)
        if role.id not in allowed_role_ids:
            await safe_send_error(
                ctx,
                "Можно звать только в роли из /role_assign — выбери одну из них.",
            )
            return

        try:
            duration = parse_minutes(
                when,
                min_minutes=settings.party.min_duration_minutes,
                max_minutes=settings.party.max_duration_minutes,
            )
        except ValueError as e:
            await safe_send_error(ctx, str(e))
            return

        if not (settings.party.min_count <= count <= settings.party.max_count):
            await safe_send_error(
                ctx,
                f"Число участников должно быть от {settings.party.min_count} "
                f"до {settings.party.max_count}.",
            )
            return

        if image is not None and not (image.content_type or "").startswith("image/"):
            await safe_send_error(ctx, "Вложение должно быть картинкой.")
            return

        initiator = ctx.author
        if not isinstance(initiator, discord.Member):
            await safe_send_error(ctx, "чел ты не в конфе")
            return

        image_url = image.url if image is not None else None
        await self._preview_and_publish(
            ctx,
            role=role,
            initiator=initiator,
            duration=duration,
            count=count,
            comment=comment,
            image_url=image_url,
        )

    async def _preview_and_publish(
        self,
        ctx: commands.Context,
        *,
        role: discord.Role,
        initiator: discord.Member,
        duration: timedelta,
        count: int,
        comment: str,
        image_url: str | None,
    ) -> None:
        """Показывает эфемерное превью и публикует сбор по подтверждению.

        В превью видно, как embed будет выглядеть; кнопки «Опубликовать» /
        «Отмена» решают судьбу. На отмене/таймауте кулдаун команды
        сбрасывается, чтобы попытка не «сгорала».
        """
        assert ctx.guild is not None  # проверено выше в party()
        now = datetime.now(UTC)
        preview_party = Party(
            id="preview",
            guild_id=ctx.guild.id,
            channel_id=ctx.channel.id,
            public_message_id=0,
            role_id=role.id,
            initiator_id=initiator.id,
            count=count,
            comment=comment,
            created_at=now,
            deadline=now + duration,
            image_url=image_url,
            joined_order=[initiator.id],
        )
        settings = get_settings()
        preview_embed = build_party_embed(
            preview_party,
            role_name=role.name,
            initiator=initiator,
            member_resolver=self._member_resolver(ctx.guild),
            initiator_emoji=settings.party.initiator_emoji,
            finalized=False,
            jump_url=None,
        )

        view = PartyPreviewView(author_id=initiator.id)
        preview_msg = await ctx.send(
            content="Так будет выглядеть сбор. Опубликовать?",
            embed=preview_embed,
            view=view,
            ephemeral=True,
        )
        await view.wait()

        if view.choice == "publish":
            await self._publish_party(
                ctx,
                role=role,
                initiator=initiator,
                duration=duration,
                count=count,
                comment=comment,
                image_url=image_url,
            )
            return

        if ctx.command is not None:
            ctx.command.reset_cooldown(ctx)
        if view.choice != "cancel" and preview_msg is not None:
            try:
                await preview_msg.edit(
                    content="Превью истекло, сбор не создан.", embed=None, view=None
                )
            except discord.HTTPException:
                pass

    async def _publish_party(
        self,
        ctx: commands.Context,
        *,
        role: discord.Role,
        initiator: discord.Member,
        duration: timedelta,
        count: int,
        comment: str,
        image_url: str | None,
    ) -> None:
        """Публикует сбор в канал, рассылает DM и заводит таймер финализации."""
        assert ctx.guild is not None
        now = datetime.now(UTC)
        deadline = now + duration

        placeholder_embed = discord.Embed(
            title=f"Сбор пати: {role.name}",
            description="Готовлю сбор…",
            color=discord.Color.green(),
        )
        try:
            public_message = await ctx.channel.send(embed=placeholder_embed)
        except discord.HTTPException as e:
            logger.error(f"Не удалось опубликовать embed пати: {e}")
            return

        party = self.manager.create(
            guild_id=ctx.guild.id,
            channel_id=public_message.channel.id,
            public_message_id=public_message.id,
            role_id=role.id,
            initiator_id=initiator.id,
            count=count,
            comment=comment,
            created_at=now,
            deadline=deadline,
            image_url=image_url,
        )

        await self._refresh_public_embed(party)

        delivered = await self._send_dms(party, role, initiator)
        # После рассылки нужно ещё раз обновить публичный embed — а заодно DM,
        # вдруг счётчики уже изменились пока мы рассылали.
        await self._refresh_all_embeds(party)
        logger.info(
            f"Создано пати {party.id} (роль {role.id}, нужно {count}, "
            f"дедлайн {deadline.isoformat()}): DM доставлено {delivered}"
        )

        seconds = max(1, int(duration.total_seconds()))
        task = asyncio.create_task(
            self._finalize_after(party, seconds), name=f"party-finalize-{party.id}"
        )
        self._timers[party.id] = task

    @commands.hybrid_command(
        name="party_cancel",
        description="Отменить свой последний активный сбор пати.",
    )
    @command_error_handler
    async def party_cancel(self, ctx: commands.Context) -> None:
        """Отменяет последний активный сбор инициатора."""
        active = self.manager.list_for_initiator(ctx.author.id)
        if not active:
            await safe_send_error(ctx, "У тебя нет активных пати.")
            return

        party = active[-1]
        for timers in (self._timers, self._check_timers):
            task = timers.pop(party.id, None)
            if task is not None:
                task.cancel()
        cancelled = await self.manager.cancel(party.id)
        # None означает что таймер _finalize уже всё снял — просто рапортуем.
        if cancelled is not None:
            await self._disable_dm_buttons(cancelled)
            await self._refresh_public_embed(cancelled)
        await safe_send(ctx, "Сбор пати отменён.", ephemeral=True)
        logger.info(f"Пати {party.id} отменено инициатором {ctx.author.id}")

    @app_commands.command(
        name="party_block",
        description="(Админ) Запретить пользователю вызывать /party.",
    )
    @app_commands.describe(user="Кого блокировать", reason="Причина (опционально)")
    @app_commands.checks.has_permissions(administrator=True)
    async def party_block(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str | None = None,
    ) -> None:
        """Добавляет пользователя в blacklist команды /party."""
        ok = await self.data_manager.add_block(
            user_id=user.id, blocked_by=interaction.user.id, reason=reason
        )
        if ok:
            suffix = f" (причина: {reason})" if reason else ""
            await interaction.response.send_message(
                f"Пользователь {user.mention} заблокирован для /party{suffix}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Не удалось заблокировать пользователя — см. логи.", ephemeral=True
            )

    @app_commands.command(
        name="party_unblock",
        description="(Админ) Снять запрет на /party.",
    )
    @app_commands.describe(user="Кого разблокировать")
    @app_commands.checks.has_permissions(administrator=True)
    async def party_unblock(self, interaction: discord.Interaction, user: discord.User) -> None:
        """Снимает блокировку пользователя."""
        ok = await self.data_manager.remove_block(user_id=user.id)
        if ok:
            await interaction.response.send_message(
                f"Пользователь {user.mention} разблокирован.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Пользователь {user.mention} не был в blacklist.", ephemeral=True
            )

    @app_commands.command(
        name="party_blocklist",
        description="(Админ) Показать заблокированных для /party пользователей.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def party_blocklist(self, interaction: discord.Interaction) -> None:
        """Выводит список заблокированных пользователей."""
        rows = await self.data_manager.list_blocks()
        if not rows:
            await interaction.response.send_message("Blacklist /party пуст.", ephemeral=True)
            return

        lines: list[str] = []
        for row in rows:
            user_id = row["user_id"]
            blocked_by = row["blocked_by"]
            reason = row["reason"] or "—"
            lines.append(f"<@{user_id}> (by <@{blocked_by}>): {reason}")

        embed = discord.Embed(
            title="Blacklist /party",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    """Регистрирует ког в боте."""
    await bot.add_cog(PartyCog(bot))
    logger.info("Ког PartyCog успешно загружен.")
