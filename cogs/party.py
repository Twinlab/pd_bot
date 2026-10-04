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
from weakref import WeakSet

import discord
from discord import app_commands
from discord.ext import commands

from config import get_settings
from utils.error_handler import command_error_handler, new_incident_id, safe_send, safe_send_error
from utils.party.data_manager import PartyDataManager
from utils.party.embeds import build_party_container, party_card_view
from utils.party.manager import Party, PartyManager, PartyPhase
from utils.party.state import PartyRecord, PartySnapshot, PartyStateStore
from utils.party.views import (
    PartyConfirmView,
    PartySetupModal,
    PartyView,
)
from utils.role_reaction_data_manager import RoleReactionDataManager
from utils.ui import colors

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

    def __init__(self, bot: commands.Bot, *, state_store: PartyStateStore | None = None) -> None:
        self.bot = bot
        self.manager = PartyManager()
        self.data_manager = PartyDataManager()
        self.role_reaction_manager = RoleReactionDataManager()
        self._timers = {}
        self._check_timers = {}
        self._last_party = {}
        self._publishing_users: set[int] = set()
        self._state_store = state_store or PartyStateStore()
        self._state_lock = asyncio.Lock()
        self._loaded = False
        self._stopping = False
        self._state_error: str | None = None
        self._closing: dict[str, Party] = {}
        self._recovering: set[str] = set()
        self._restore_task: asyncio.Task[None] | None = None
        self._views: WeakSet[discord.ui.LayoutView] = WeakSet()
        self._broadcasting: set[str] = set()
        self._broadcast_tasks: set[asyncio.Task[int]] = set()

    def ensure_available(self, party_id: str | None = None) -> None:
        """Запрещает менять состояние до восстановления и после ошибки хранилища."""
        if not self._loaded or self._stopping or self._state_error or party_id in self._recovering:
            raise RuntimeError("Состояние сборов недоступно; дождитесь восстановления бота")

    def _fail_state(self, error: Exception) -> None:
        self._state_error = self._state_error or new_incident_id()
        logger.error(
            "Хранилище сборов недоступно [%s]; изменения заблокированы",
            self._state_error,
            exc_info=(type(error), error, error.__traceback__),
            extra={"context": {"incident_id": self._state_error}},
        )

    async def _persist_locked(self) -> None:
        if not self._loaded or self._state_error:
            raise RuntimeError("Нельзя перезаписать недоступное состояние сборов")
        try:
            snapshot = PartySnapshot(
                version=1,
                parties=[
                    PartyRecord.from_party(party)
                    for party in [*self.manager.all_active(), *self._closing.values()]
                ],
                cooldowns=self._last_party,
            )
            await self._state_store.save(snapshot)
        except Exception as error:
            self._fail_state(error)
            raise

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Запускает одно восстановление; reconnect не загружает снимок повторно."""
        if self._restore_task is None and not self._stopping:
            self._restore_task = asyncio.create_task(self._restore_loop(), name="party-restore")

    async def cog_load(self) -> None:
        """Восстанавливает сборы и при перезагрузке кога уже работающего бота."""
        if self.bot.is_ready():
            await self.on_ready()

    async def _restore_loop(self) -> None:
        try:
            async with self._state_lock:
                snapshot = await asyncio.to_thread(self._state_store.load)
                guild_id = get_settings().guild_id
                if guild_id and any(record.guild_id != guild_id for record in snapshot.parties):
                    raise ValueError("Снимок сборов относится к другому серверу")
                parties = [record.to_party() for record in snapshot.parties]
                self.manager.restore(parties)
                self._closing = {party.id: party for party in parties if party.finalized}
                self._last_party = dict(snapshot.cooldowns)
                self._recovering = {party.id for party in parties}
                self._loaded = True
            while not self._stopping and not self._state_error:
                for party_id in tuple(self._recovering):
                    party = self.manager.get(party_id) or self._closing.get(party_id)
                    if party is None or await self._restore_party(party):
                        self._recovering.discard(party_id)
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail_state(error)

    async def _restore_party(self, party: Party) -> bool:
        if party.id in self._broadcasting:
            return False
        async with self._state_lock:
            now = datetime.now(UTC)
            close = party.deadline <= now
            changed = False
            if not party.finalized and not close and party.phase is PartyPhase.READY_CHECK:
                tick = await self.manager.tick_ready_check(
                    party.id,
                    now=now,
                    window=timedelta(seconds=get_settings().party.confirm_window_seconds),
                )
                changed = tick.changed
                close = tick.finished in ("success", "partial")
            if not party.finalized and close:
                await self.manager.cancel(party.id)
                party.final_notice_attempted = True
                self._closing[party.id] = party
                changed = True
            if changed:
                await self._persist_locked()
        guild = self.bot.get_guild(party.guild_id)
        if guild is None:
            return False
        try:
            missing_public = False
            public_accessible = True
            try:
                channel = self.bot.get_channel(party.channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(party.channel_id)
                if not isinstance(
                    channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)
                ):
                    raise ValueError("Сохранённый канал сбора недоступен")
                await channel.fetch_message(party.public_message_id)
            except discord.NotFound:
                missing_public = True
            except discord.HTTPException:
                public_accessible = False
            restored: dict[int, discord.Message] = {}
            missing: list[int] = []
            for user_id, (channel_id, message_id) in tuple(party.dm_message_ids.items()):
                try:
                    user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                    dm = await user.create_dm()
                    if dm.id != channel_id:
                        raise ValueError("Сохранённое приглашение не принадлежит участнику")
                    restored[user_id] = await dm.fetch_message(message_id)
                except discord.NotFound:
                    missing.append(user_id)
                except discord.HTTPException as error:
                    logger.warning("Не удалось восстановить DM сбора %s: %s", party.id, error)
            async with self._state_lock:
                party.dm_messages.update(restored)
                for user_id in missing:
                    party.dm_message_ids.pop(user_id, None)
                    party.dm_messages.pop(user_id, None)
                if missing_public and not party.finalized:
                    await self.manager.cancel(party.id)
                    party.final_notice_attempted = True
                    self._closing[party.id] = party
                if missing or missing_public:
                    await self._persist_locked()
            if party.finalized or party.deadline <= datetime.now(UTC):
                await self._finalize(party, notify=False)
                return party.id not in self._closing
            if not public_accessible or not party.dm_message_ids.keys() <= party.dm_messages.keys():
                return False
            public_ok = await self._refresh_public_embed(party)
            dm_ok = await self._refresh_dm_embeds(party)
            if public_ok is False or dm_ok is False:
                return False
            if party.id not in self._timers:
                self._timers[party.id] = asyncio.create_task(
                    self._finalize_after(party), name=f"party-finalize-{party.id}"
                )
            if party.phase is PartyPhase.READY_CHECK:
                self._start_check_loop(party)
            else:
                await self._maybe_start_ready_check(party)
            return True
        except (discord.HTTPException, ValueError) as error:
            logger.warning("Не удалось восстановить сообщения сбора %s: %s", party.id, error)
            return False

    async def _allowed_role_ids(self, guild_id: int) -> set[int]:
        """ID ролей, разрешённых для сбора (только выданные через /role_assign).

        Системная запись с ``role_id == 0`` отфильтровывается — это маркер
        самого role-message, не настоящая роль.
        """
        rows = await self.role_reaction_manager.get_all_role_reactions(guild_id)
        return {row["role_id"] for row in rows if row["role_id"] != 0}

    async def cog_unload(self) -> None:
        """Останавливает задачи и сохраняет сборы для следующего запуска."""
        self._stopping = True
        tasks = [*self._timers.values(), *self._check_timers.values()]
        if self._restore_task is not None:
            tasks.append(self._restore_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._broadcast_tasks:
            # Уже принятый Discord DM нужно записать до передачи файла новому когу.
            await asyncio.gather(*self._broadcast_tasks, return_exceptions=True)
        self._timers.clear()
        self._check_timers.clear()

        for view in self._views:
            view.stop()
        self._views.clear()
        async with self._state_lock:
            if self._loaded and not self._state_error:
                await self._persist_locked()
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

    def _build_container(
        self, party: Party, *, finalized: bool | None = None
    ) -> discord.ui.Container:
        """Готовит CV2-контейнер для конкретного состояния пати."""
        settings = get_settings()
        guild = self.bot.get_guild(party.guild_id)
        role = guild.get_role(party.role_id) if guild else None
        initiator = self._member_resolver(guild)(party.initiator_id)
        jump_url = (
            f"https://discord.com/channels/{party.guild_id}/{party.channel_id}"
            f"/{party.public_message_id}"
        )
        return build_party_container(
            party,
            role_name=role.name if role else f"роль #{party.role_id}",
            initiator=initiator,
            member_resolver=self._member_resolver(guild),
            initiator_emoji=settings.party.initiator_emoji,
            finalized=party.finalized if finalized is None else finalized,
            jump_url=jump_url,
        )

    def _card_view(self, party: Party, *, finalized: bool | None = None) -> discord.ui.LayoutView:
        """Неинтерактивная карточка сбора (публичное сообщение, финал в DM)."""
        return party_card_view(self._build_container(party, finalized=finalized))

    async def _refresh_public_embed(self, party: Party) -> bool:
        """Перерисовывает публичную карточку; поглощает Discord-ошибки."""
        guild = self.bot.get_guild(party.guild_id)
        channel = self.bot.get_channel(party.channel_id) if guild else None
        try:
            if channel is None:
                channel = await self.bot.fetch_channel(party.channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
                return False
            message = await channel.fetch_message(party.public_message_id)
        except discord.NotFound:
            return True
        except discord.HTTPException as e:
            logger.warning(f"fetch_message {party.public_message_id} упал: {e}")
            return False

        try:
            was_finalized = party.finalized
            await message.edit(view=self._card_view(party))
            if not was_finalized and party.finalized:
                await message.edit(view=self._card_view(party, finalized=True))
        except discord.NotFound:
            return True
        except discord.HTTPException as e:
            logger.warning(f"Не удалось обновить публичную карточку пати {party.id}: {e}")
            return False
        return True

    async def _refresh_dm_embeds(self, party: Party) -> bool:
        """Перерисовывает карточку во всех DM с корректным для фазы/юзера view."""
        if not party.dm_messages:
            return True

        async def edit_one(uid: int, msg: discord.Message) -> bool:
            try:
                was_finalized = party.finalized
                await msg.edit(view=self._dm_view_for(party, uid))
                # Более медленное обновление не должно вернуть кнопки после финального.
                if not was_finalized and party.finalized:
                    await msg.edit(view=self._card_view(party, finalized=True))
            except discord.NotFound:
                return True
            except discord.HTTPException as e:
                logger.warning(f"DM edit для юзера {uid} упал: {e}")
                return False
            return True

        results = await asyncio.gather(
            *(edit_one(uid, msg) for uid, msg in party.dm_messages.items()),
            return_exceptions=True,
        )
        return all(result is True for result in results)

    async def _refresh_all_embeds(self, party: Party) -> None:
        """Обновляет публичную карточку + все DM синхронно."""
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
        """Не даёт финализатору забыть ещё отправляемое приглашение."""
        self._broadcasting.add(party.id)
        task = asyncio.current_task()
        if task is not None:
            self._broadcast_tasks.add(task)
        try:
            return await self._send_dms_impl(party, role, initiator)
        finally:
            self._broadcasting.discard(party.id)
            if task is not None:
                self._broadcast_tasks.discard(task)

    async def _send_dms_impl(
        self,
        party: Party,
        role: discord.Role,
        initiator: discord.Member,
    ) -> int:
        """Рассылает DM с embed + кнопками. Возвращает число доставленных писем."""
        settings = get_settings()
        delivered = 0
        for member in role.members:
            if (
                self._stopping
                or self._state_error
                or party.finalized
                or datetime.now(UTC) >= party.deadline
            ):
                break
            if member.bot or member.id == initiator.id:
                continue
            if await self.data_manager.is_blocked(member.id):
                continue
            if (
                self._stopping
                or self._state_error
                or party.finalized
                or datetime.now(UTC) >= party.deadline
            ):
                break
            try:
                view = PartyView(cog=self, party=party)
                msg = await member.send(view=view)
                async with self._state_lock:
                    party.dm_messages[member.id] = msg
                    party.dm_message_ids[member.id] = (msg.channel.id, msg.id)
                    if party.finalized:
                        self._closing[party.id] = party
                        self._recovering.add(party.id)
                    await self._persist_locked()
                delivered += 1
                # Финализация могла пройти, пока Discord отправлял это сообщение.
                if party.finalized:
                    await msg.edit(view=self._card_view(party, finalized=True))
                    break
            except discord.Forbidden:
                logger.info(f"Юзер {member.id} закрыл DM — пропускаем")
            except discord.HTTPException as e:
                logger.warning(f"Ошибка отправки DM юзеру {member.id}: {e}")
            await asyncio.sleep(settings.party.dm_send_delay)
        return delivered

    async def _disable_dm_buttons(self, party: Party) -> bool:
        """Снимает кнопки во всех DM, заменяя на серую карточку-финал."""
        if not party.dm_messages:
            return True

        async def disable_one(uid: int, msg: discord.Message) -> bool:
            try:
                await msg.edit(view=self._card_view(party, finalized=True))
            except discord.NotFound:
                return True
            except discord.HTTPException as e:
                logger.warning(f"Не удалось снять кнопки в DM юзера {uid}: {e}")
                return False
            return True

        results = await asyncio.gather(
            *(disable_one(uid, msg) for uid, msg in party.dm_messages.items()),
            return_exceptions=True,
        )
        return all(result is True for result in results)

    def _dm_view_for(self, party: Party, user_id: int) -> discord.ui.LayoutView:
        """Подбирает DM-view под фазу/роль юзера.

        В чеке: подтвердившим — карточка без кнопок, ожидающим подтверждения —
        «Подтверждаю», остальным (резерв) — обычные «Готов» / «Не готов».
        """
        if party.finalized:
            return self._card_view(party, finalized=True)
        if party.phase is PartyPhase.READY_CHECK:
            if user_id in party.confirmed:
                return self._card_view(party)
            if party.is_candidate(user_id):
                return PartyConfirmView(cog=self, party=party)
        return PartyView(cog=self, party=party)

    async def _sync_check_views(self, party: Party) -> None:
        """Перерисовывает все DM с корректным для каждого юзера view (фаза чека)."""
        await self._refresh_dm_embeds(party)

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
        if not party.finish_when_full or not settings.party.enable_ready_check:
            return
        window = timedelta(seconds=settings.party.confirm_window_seconds)
        async with self._state_lock:
            self.ensure_available()
            if party.deadline <= datetime.now(UTC):
                return
            started = await self.manager.start_ready_check(
                party.id, now=datetime.now(UTC), window=window
            )
            if started is not None:
                await self._persist_locked()
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
        if party.id in self._check_timers:
            return
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
                if party.deadline <= datetime.now(UTC):
                    await self._finalize(party)
                    return
                async with self._state_lock:
                    self.ensure_available()
                    tick = await self.manager.tick_ready_check(
                        party.id, now=datetime.now(UTC), window=window
                    )
                    if tick.changed:
                        await self._persist_locked()
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
        except Exception:
            logger.exception("Остановлена проверка готовности сбора %s", party.id)

    async def _after_confirm(self, party: Party) -> None:
        """Реакция на нажатие «Подтверждаю»: перерисовка и финал при полном составе."""
        await self._sync_check_views(party)
        await self._refresh_public_embed(party)
        if len(party.confirmed) >= party.count:
            await self._finalize(party)

    async def _finalize_after(self, party: Party) -> None:
        """Таймер закрытия пати. Отменяется через `task.cancel()` в `cog_unload`."""
        try:
            seconds = max(0.0, (party.deadline - datetime.now(UTC)).total_seconds())
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        try:
            await self._finalize(party)
        except Exception:
            logger.exception("Не удалось завершить сбор %s", party.id)

    async def _finalize(self, party: Party, *, notify: bool = True) -> None:
        """Финализирует пати: пингует готовых, обновляет embed, чистит state."""
        settings = get_settings()
        guild = self.bot.get_guild(party.guild_id)
        channel = self.bot.get_channel(party.channel_id) if guild else None
        role = guild.get_role(party.role_id) if guild else None

        # cancel() атомарно помечает финализированным и удаляет из активных —
        # снимок ростера берём только после него, чтобы поздний клик не потерялся.
        async with self._state_lock:
            self.ensure_available()
            cancelled = await self.manager.cancel(party.id)
            if cancelled is not None:
                self._closing[party.id] = cancelled
            else:
                cancelled = self._closing.get(party.id)
            if cancelled is None:
                return
            send_notice = notify and not cancelled.final_notice_attempted
            # При неясном результате send не повторяем пинг после рестарта.
            cancelled.final_notice_attempted = True
            await self._persist_locked()

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

        if send_notice and isinstance(
            channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)
        ):
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
        closing_ids = dict(cancelled.dm_message_ids)
        dm_ok = await self._disable_dm_buttons(cancelled)
        public_ok = await self._refresh_public_embed(cancelled)
        async with self._state_lock:
            if self._stopping:
                # Старый callback может завершить HTTP после выгрузки: marker уже сохранён.
                return
            if (
                dm_ok is not False
                and public_ok is not False
                and closing_ids == cancelled.dm_message_ids
                and closing_ids.keys() <= cancelled.dm_messages.keys()
                and party.id not in self._broadcasting
            ):
                self._closing.pop(party.id, None)
                self._recovering.discard(party.id)
            else:
                self._recovering.add(party.id)
            await self._persist_locked()
        deadline_task = self._timers.pop(party.id, None)
        if deadline_task is not None and deadline_task is not asyncio.current_task():
            deadline_task.cancel()
        check_task = self._check_timers.pop(party.id, None)
        # Отменяем sweep, только если финал пришёл не из него самого.
        if check_task is not None and check_task is not asyncio.current_task():
            check_task.cancel()

    def _party_cooldown_remaining(self, user_id: int) -> int:
        """Сколько секунд осталось до следующего разрешённого сбора (0 — можно).

        Кулдаун специально привязан к ФАКТУ публикации пати (см. ``_last_party``),
        а не к вызову ``/party``: команда лишь открывает эфемерный мастер, и
        пользователь может открыть/закрыть его сколько угодно раз, пока ничего не
        опубликовал. Поэтому ``@app_commands.checks.cooldown`` (кулдаун на вызов)
        здесь не подходит — он банил бы и тех, кто просто передумал в мастере.
        """
        last = self._last_party.get(user_id)
        if last is None:
            return 0
        elapsed = (datetime.now(UTC) - last).total_seconds()
        remaining = get_settings().party.command_cooldown_seconds - elapsed
        return max(0, int(remaining))

    def build_party_preview_container(
        self,
        *,
        role: discord.Role | None,
        initiator: discord.Member,
        duration: timedelta,
        count: int,
        comment: str,
        image_url: str | None,
        finish_when_full: bool,
    ) -> discord.ui.Container:
        """Строит CV2-контейнер-превью сбора (как он будет выглядеть после публикации)."""
        now = datetime.now(UTC)
        preview_party = Party(
            id="preview",
            guild_id=initiator.guild.id,
            channel_id=0,
            public_message_id=0,
            role_id=role.id if role else 0,
            initiator_id=initiator.id,
            count=count,
            comment=comment,
            created_at=now,
            deadline=now + duration,
            image_url=image_url,
            finish_when_full=finish_when_full,
            joined_order=[initiator.id],
        )
        settings = get_settings()
        container = build_party_container(
            preview_party,
            role_name=role.name if role else "роль",
            initiator=initiator,
            member_resolver=self._member_resolver(initiator.guild),
            initiator_emoji=settings.party.initiator_emoji,
            finalized=False,
            jump_url=None,
        )
        container.add_item(discord.ui.TextDisplay("-# Так будет выглядеть сбор"))
        return container

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
        finish_when_full: bool,
    ) -> Party | None:
        """Публикует сбор в канал, рассылает DM и заводит таймер финализации.

        Не зависит от ``commands.Context`` — годится и для слэш-панели, и для
        обычной команды. Возвращает созданный :class:`Party` или ``None``,
        если публичное сообщение отправить не удалось.
        """
        now = datetime.now(UTC)
        deadline = now + duration
        self.ensure_available()

        placeholder_view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=None)
        placeholder_container: discord.ui.Container = discord.ui.Container(
            accent_colour=colors.SUCCESS
        )
        placeholder_container.add_item(discord.ui.TextDisplay(f"## Сбор пати: {role.name}"))
        placeholder_container.add_item(discord.ui.TextDisplay("Готовлю сбор…"))
        placeholder_view.add_item(placeholder_container)
        try:
            public_message = await channel.send(view=placeholder_view)
        except discord.HTTPException as e:
            logger.error(f"Не удалось опубликовать карточку пати: {e}")
            return None

        async with self._state_lock:
            self.ensure_available()
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
                finish_when_full=finish_when_full,
            )
            self._last_party[initiator.id] = now
            await self._persist_locked()
        self._timers[party.id] = asyncio.create_task(
            self._finalize_after(party), name=f"party-finalize-{party.id}"
        )

        await self._refresh_public_embed(party)

        delivered = await self._send_dms(party, role, initiator)
        # После рассылки нужно ещё раз обновить публичный embed — а заодно DM,
        # вдруг счётчики уже изменились пока мы рассылали.
        if not self._stopping and not party.finalized:
            await self._refresh_all_embeds(party)
        logger.info(
            f"Создано пати {party.id} (роль {role.id}, нужно {count}, "
            f"дедлайн {deadline.isoformat()}, finish_when_full={finish_when_full}): "
            f"DM доставлено {delivered}"
        )

        if not self._stopping and not party.finalized:
            await self._maybe_start_ready_check(party)
        return party

    @app_commands.command(
        name="party",
        description="Собрать пати: позвать людей с нужной ролью в стак.",
    )
    @app_commands.describe(image="Картинка к сбору (опционально)")
    async def party(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment | None = None,
    ) -> None:
        """Открывает модалку сбора пати (Modal v2)."""
        if not self._loaded or self._stopping or self._state_error:
            await safe_send_error(
                interaction, "Сборы пока недоступны. Попробуй после восстановления бота."
            )
            return
        guild = interaction.guild
        if guild is None:
            await safe_send_error(interaction, "Только в конфе, чел.")
            return

        initiator = interaction.user
        if not isinstance(initiator, discord.Member):
            await safe_send_error(interaction, "Ты не в конфе.")
            return

        if await self.data_manager.is_blocked(initiator.id):
            await safe_send_error(interaction, "ты в бане")
            return

        remaining = self._party_cooldown_remaining(initiator.id)
        if remaining > 0:
            await safe_send_error(
                interaction,
                f"Слишком часто — следующий сбор можно через {remaining // 60} мин "
                f"{remaining % 60} сек.",
            )
            return

        allowed_role_ids = await self._allowed_role_ids(guild.id)
        roles = [role for rid in allowed_role_ids if (role := guild.get_role(rid)) is not None]
        if not roles:
            await safe_send_error(interaction, "Нет доступных ролей из /role_assign.")
            return

        if image is not None and not (image.content_type or "").startswith("image/"):
            await safe_send_error(interaction, "Вложение должно быть картинкой.")
            return

        await interaction.response.send_modal(
            PartySetupModal(
                cog=self,
                initiator=initiator,
                roles=roles,
                image_url=image.url if image is not None else None,
            )
        )

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
        await self._finalize(party, notify=False)
        await safe_send(ctx, "Сбор пати отменён.", ephemeral=True)
        logger.info(f"Пати {party.id} отменено инициатором {ctx.author.id}")

    @app_commands.command(
        name="party_block",
        description="(Админ) Запретить пользователю вызывать /party.",
    )
    @app_commands.describe(user="Кого блокировать", reason="Причина (опционально)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
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
            await safe_send_error(interaction, "Не удалось заблокировать пользователя — см. логи.")

    @app_commands.command(
        name="party_unblock",
        description="(Админ) Снять запрет на /party.",
    )
    @app_commands.describe(user="Кого разблокировать (выбор из списка заблокированных)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def party_unblock(self, interaction: discord.Interaction, user: str) -> None:
        """Снимает блокировку пользователя.

        ``user`` — строковый Discord ID из автокомплита: нативный пикер
        ``discord.User`` не поддерживает автокомплит, поэтому берём id строкой и
        подсказываем только реально заблокированных (см. ``party_unblock_autocomplete``).
        """
        try:
            user_id = int(user)
        except ValueError:
            await safe_send_error(interaction, "Некорректный пользователь.")
            return

        ok = await self.data_manager.remove_block(user_id=user_id)
        message = (
            f"Пользователь <@{user_id}> разблокирован."
            if ok
            else f"Пользователь <@{user_id}> не был в blacklist."
        )
        await interaction.response.send_message(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @party_unblock.autocomplete("user")
    async def party_unblock_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Подсказывает при разблокировке только реально заблокированных юзеров."""
        try:
            rows = await self.data_manager.list_blocks()
        except Exception as e:
            logger.debug(f"Автокомплит party_unblock не смог получить blacklist: {e}")
            return []

        cur = current.lower().strip()
        choices: list[app_commands.Choice[str]] = []
        for row in rows:
            user_id = int(row["user_id"])  # type: ignore[call-overload]
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            label = member.display_name if member else str(user_id)
            reason = row["reason"]
            name = f"{label} — {reason}" if reason else label
            if cur and cur not in name.lower() and cur not in str(user_id):
                continue
            choices.append(app_commands.Choice(name=name[:100], value=str(user_id)))
        return choices[:25]

    @app_commands.command(
        name="party_blocklist",
        description="(Админ) Показать заблокированных для /party пользователей.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
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
