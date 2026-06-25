"""Ког сбора пати в игры через DM-кнопки.

Команда ``/party`` открывает пошаговый эфемерный мастер: **роль** (выпадушка)
→ **параметры** (модалка со свободным вводом времени, состава и комментария)
→ **превью** с кнопкой **Опубликовать**. После публикации создаётся публичный
embed в канале и рассылаются DM каждому участнику с указанной серверной ролью.
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
from utils.party.embeds import build_party_embed
from utils.party.manager import Party, PartyManager, PartyPhase
from utils.party.views import (
    PartyBuilderView,
    PartyConfirmView,
    PartyView,
)
from utils.role_reaction_data_manager import RoleReactionDataManager

logger = logging.getLogger("bot.cogs.party")


class PartyCog(commands.Cog):
    """Сбор пати: команды + кнопки в DM + таймеры финализации."""

    bot: commands.Bot
    manager: PartyManager
    data_manager: PartyDataManager
    role_reaction_manager: RoleReactionDataManager
    _timers: dict[str, asyncio.Task[None]]
    _check_timers: dict[str, asyncio.Task[None]]
    _last_party: dict[int, datetime]

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = PartyManager()
        self.data_manager = PartyDataManager()
        self.role_reaction_manager = RoleReactionDataManager()
        self._timers = {}
        self._check_timers = {}
        self._last_party = {}

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

    async def _nudge_user(self, party: Party, user_id: int, text: str) -> None:
        """Шлёт в DM отдельным сообщением пинг юзеру с просьбой подтвердиться."""
        msg = party.dm_messages.get(user_id)
        if msg is None:
            return
        try:
            await msg.channel.send(f"<@{user_id}> {text}")
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
        request = settings.party.confirm_request_message
        await asyncio.gather(
            *(self._nudge_user(started, uid, request) for uid in started.pending_confirm),
            return_exceptions=True,
        )
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
                    nudge = settings.party.confirm_nudge_message
                    for uid in tick.promoted:
                        await self._nudge_user(party, uid, nudge)
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
                    role=role_name, comment=cancelled.comment, ready_pings=ready_pings
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
            ready_pings = " ".join(f"<@{uid}>" for uid in roster)
            if len(roster) >= cancelled.count:
                text = settings.party.finished_message_template.format(
                    ready_pings=ready_pings, role=role_name, comment=cancelled.comment
                )
            else:
                # Состав не набран, но пингуем тех, кто всё же был готов.
                text = settings.party.empty_finished_message.format(
                    role=role_name, comment=cancelled.comment, ready_pings=ready_pings
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

    def _party_cooldown_remaining(self, user_id: int) -> int:
        """Сколько секунд осталось до следующего разрешённого сбора (0 — можно)."""
        last = self._last_party.get(user_id)
        if last is None:
            return 0
        elapsed = (datetime.now(UTC) - last).total_seconds()
        remaining = get_settings().party.command_cooldown_seconds - elapsed
        return max(0, int(remaining))

    def build_party_preview_embed(
        self,
        *,
        role: discord.Role,
        initiator: discord.Member,
        duration: timedelta,
        count: int,
        comment: str,
        image_url: str | None,
    ) -> discord.Embed:
        """Строит embed-превью сбора (как он будет выглядеть после публикации)."""
        now = datetime.now(UTC)
        preview_party = Party(
            id="preview",
            guild_id=initiator.guild.id,
            channel_id=0,
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
        return build_party_embed(
            preview_party,
            role_name=role.name,
            initiator=initiator,
            member_resolver=self._member_resolver(initiator.guild),
            initiator_emoji=settings.party.initiator_emoji,
            finalized=False,
            jump_url=None,
        )

    async def _create_and_broadcast(
        self,
        *,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        role: discord.Role,
        initiator: discord.Member,
        duration: timedelta,
        count: int,
        comment: str,
        image_url: str | None,
    ) -> Party | None:
        """Публикует сбор в канал, рассылает DM и заводит таймер финализации.

        Не зависит от ``commands.Context`` — годится и для слэш-панели, и для
        обычной команды. Возвращает созданный :class:`Party` или ``None``,
        если публичное сообщение отправить не удалось.
        """
        now = datetime.now(UTC)
        deadline = now + duration

        placeholder_embed = discord.Embed(
            title=f"Сбор пати: {role.name}",
            description="Готовлю сбор…",
            color=discord.Color.green(),
        )
        try:
            public_message = await channel.send(embed=placeholder_embed)
        except discord.HTTPException as e:
            logger.error(f"Не удалось опубликовать embed пати: {e}")
            return None

        party = self.manager.create(
            guild_id=guild.id,
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
        self._last_party[initiator.id] = now
        return party

    @app_commands.command(
        name="party",
        description="Собрать пати: пошаговый мастер (роль → параметры → публикация).",
    )
    @app_commands.describe(image="Картинка к сбору (опционально)")
    async def party(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment | None = None,
    ) -> None:
        """Открывает пошаговый эфемерный мастер сбора пати."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Только в конфе, чел.", ephemeral=True)
            return

        initiator = interaction.user
        if not isinstance(initiator, discord.Member):
            await interaction.response.send_message("Ты не в конфе.", ephemeral=True)
            return

        if await self.data_manager.is_blocked(initiator.id):
            await interaction.response.send_message("ты в бане", ephemeral=True)
            return

        remaining = self._party_cooldown_remaining(initiator.id)
        if remaining > 0:
            await interaction.response.send_message(
                f"Слишком часто — следующий сбор можно через {remaining // 60} мин "
                f"{remaining % 60} сек.",
                ephemeral=True,
            )
            return

        allowed_role_ids = await self._allowed_role_ids(guild.id)
        roles = [role for rid in allowed_role_ids if (role := guild.get_role(rid)) is not None]
        if not roles:
            await interaction.response.send_message(
                "Нет доступных ролей из /role_assign.", ephemeral=True
            )
            return

        if image is not None and not (image.content_type or "").startswith("image/"):
            await interaction.response.send_message(
                "Вложение должно быть картинкой.", ephemeral=True
            )
            return

        view = PartyBuilderView(
            cog=self,
            author_id=initiator.id,
            initiator=initiator,
            roles=roles,
            image_url=image.url if image is not None else None,
        )
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

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
