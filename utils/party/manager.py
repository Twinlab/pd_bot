"""In-memory state-менеджер активных пати.

Хранит структуру :class:`Party` для каждого активного сбора. Никаких I/O —
модуль чистый, что упрощает unit-тестирование без Discord/БД.

Жизненный цикл: фаза ``COLLECTING`` (нажимают «Готов» / «Не готов» в DM) →
при заполнении основного состава ``READY_CHECK`` (каждый из основы ещё раз
жмёт «Подтверждаю»; кто не успел за окно — выбывает, его слот занимает
первый из начинки) → финализация через :meth:`PartyManager.cancel`.
"""

from __future__ import annotations

import asyncio
import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


class PartyPhase(enum.Enum):
    """Фаза жизненного цикла сбора."""

    COLLECTING = "collecting"
    READY_CHECK = "ready_check"


@dataclass
class ReadyCheckTick:
    """Результат одного прохода чек-таймера (:meth:`PartyManager.tick_ready_check`).

    Attributes:
        changed: Состояние реально изменилось — нужно перерисовать embed.
        promoted: ID юзеров, которым в этот проход открылось окно подтверждения
            (первый раз в основе — им шлём DM-нудж).
        dropped: ID юзеров, выбывших из основы по таймауту подтверждения.
        finished: ``None`` — чек продолжается; ``"success"`` — состав полностью
            подтверждён; ``"partial"`` — больше некем заполнять, пора закрывать
            частичным составом.
    """

    changed: bool = False
    promoted: list[int] = field(default_factory=list)
    dropped: list[int] = field(default_factory=list)
    finished: str | None = None


@dataclass
class Party:
    """Состояние одного активного сбора пати.

    Attributes:
        id: Уникальный идентификатор сбора (UUID4 hex).
        guild_id: Сервер, на котором запущен сбор.
        channel_id: Канал, где висит публичный embed.
        public_message_id: ID публичного embed-сообщения.
        role_id: Роль, по которой шла DM-рассылка.
        initiator_id: Discord ID инициатора (он же первый в готовых).
        count: Сколько человек требуется в основной состав (включая инициатора).
        comment: Комментарий, переданный в команду /party.
        created_at: Момент создания пати.
        deadline: Момент, в который сбор должен закрыться.
        image_url: Ссылка на картинку-вложение (или None).
        finish_when_full: Запускать ли подтверждение и закрывать сбор досрочно
            после заполнения основного состава.
        joined_order: ID юзеров в порядке нажатия «Готов» (FIFO для ready/bench).
        declined_order: ID юзеров, нажавших «Не готов».
        dm_messages: ``user_id -> discord.Message`` — DM-сообщение каждого
            юзера (нужно, чтобы синхронно обновлять embed во всех личках).
        last_press: ``user_id -> момент последнего нажатия`` — для кулдауна
            между нажатиями кнопок.
        phase: Текущая фаза (:class:`PartyPhase`).
        confirmed: ID юзеров, подтвердивших готовность в фазе ``READY_CHECK``.
        confirm_deadlines: ``user_id -> дедлайн подтверждения`` для тех, кто
            сейчас в основе и ещё не подтвердил.
        not_confirmed: ID юзеров, выбывших из основы из-за неподтверждения.
        ready_check_started: Был ли вообще запущен чек готовности (влияет на
            то, по какому списку пинговать в финале).
        finalized: Флаг, что таймер уже сработал и пати закрыт.
    """

    id: str
    guild_id: int
    channel_id: int
    public_message_id: int
    role_id: int
    initiator_id: int
    count: int
    comment: str
    created_at: datetime
    deadline: datetime
    image_url: str | None = None
    finish_when_full: bool = False
    joined_order: list[int] = field(default_factory=list)
    declined_order: list[int] = field(default_factory=list)
    dm_messages: dict[int, discord.Message] = field(default_factory=dict)
    last_press: dict[int, datetime] = field(default_factory=dict)
    phase: PartyPhase = PartyPhase.COLLECTING
    confirmed: list[int] = field(default_factory=list)
    confirm_deadlines: dict[int, datetime] = field(default_factory=dict)
    not_confirmed: list[int] = field(default_factory=list)
    ready_check_started: bool = False
    finalized: bool = False

    @property
    def ready(self) -> list[int]:
        """ID юзеров в основном составе (первые ``count`` в FIFO)."""
        return self.joined_order[: self.count]

    @property
    def bench(self) -> list[int]:
        """ID юзеров в начинке (всё, что выше ``count``)."""
        return self.joined_order[self.count :]

    @property
    def declined(self) -> list[int]:
        """ID юзеров, отказавшихся."""
        return list(self.declined_order)

    @property
    def pending_confirm(self) -> list[int]:
        """ID юзеров из основы, ждущих подтверждения (в порядке очереди)."""
        return [uid for uid in self.ready if uid in self.confirm_deadlines]

    def is_candidate(self, user_id: int) -> bool:
        """True, если юзер сейчас в основе и от него ждут подтверждения."""
        return user_id in self.ready and user_id in self.confirm_deadlines


class PartyManager:
    """Коллекция активных пати с лукапом по id.

    Все мутирующие операции идут под общим :class:`asyncio.Lock`, чтобы
    быстрая серия кликов не перемешала очереди ``joined_order`` /
    ``confirmed`` / ``confirm_deadlines``.
    """

    def __init__(self) -> None:
        self._active: dict[str, Party] = {}
        # Лениво — на момент __init__ event loop может ещё не существовать.
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def create(
        self,
        *,
        guild_id: int,
        channel_id: int,
        public_message_id: int,
        role_id: int,
        initiator_id: int,
        count: int,
        comment: str,
        created_at: datetime,
        deadline: datetime,
        image_url: str | None = None,
        finish_when_full: bool = False,
    ) -> Party:
        """Создаёт новую :class:`Party`. Инициатор сразу в ``joined_order``."""
        party = Party(
            id=uuid.uuid4().hex,
            guild_id=guild_id,
            channel_id=channel_id,
            public_message_id=public_message_id,
            role_id=role_id,
            initiator_id=initiator_id,
            count=count,
            comment=comment,
            created_at=created_at,
            deadline=deadline,
            image_url=image_url,
            finish_when_full=finish_when_full,
            joined_order=[initiator_id],
        )
        self._active[party.id] = party
        return party

    async def mark_ready(self, party_id: str, user_id: int) -> Party | None:
        """Юзер нажал «Готов».

        Возвращает :class:`Party` если состояние реально изменилось (надо
        перерисовать embed), иначе ``None`` (пати не найден, закрыт или юзер
        уже готов). Работает и в фазе чека: новый «Готов» уходит в начинку —
        резерв, из которого добирают слоты выбывших.
        """
        async with self._get_lock():
            party = self._active.get(party_id)
            if party is None or party.finalized:
                return None

            was_declined = user_id in party.declined_order
            already_ready = user_id in party.joined_order

            if already_ready and not was_declined:
                return None  # ничего не поменялось

            if was_declined:
                party.declined_order.remove(user_id)
            if not already_ready:
                party.joined_order.append(user_id)
            return party

    async def mark_declined(self, party_id: str, user_id: int) -> Party | None:
        """Юзер нажал «Не готов».

        Работает в любой фазе: если юзер успел попасть в основу/подтверждённых,
        его оттуда убираем (на следующем проходе чека слот заполнит начинка).
        Инициатор отказаться не может.
        """
        async with self._get_lock():
            party = self._active.get(party_id)
            if party is None or party.finalized:
                return None
            if user_id == party.initiator_id:
                return None

            was_ready = user_id in party.joined_order
            already_declined = user_id in party.declined_order

            if already_declined and not was_ready:
                return None

            if was_ready:
                party.joined_order.remove(user_id)
            party.confirm_deadlines.pop(user_id, None)
            if user_id in party.confirmed:
                party.confirmed.remove(user_id)
            if not already_declined:
                party.declined_order.append(user_id)
            return party

    async def start_ready_check(
        self, party_id: str, *, now: datetime, window: timedelta
    ) -> Party | None:
        """Переводит сбор в фазу ``READY_CHECK``.

        Инициатор подтверждён автоматически; остальным из основы открывается
        личное окно подтверждения ``now + window``. Возвращает ``None``, если
        пати недоступен, уже в чеке или основа ещё не набрана.
        """
        async with self._get_lock():
            party = self._active.get(party_id)
            if party is None or party.finalized:
                return None
            if not party.finish_when_full:
                return None
            if party.phase is PartyPhase.READY_CHECK:
                return None
            if len(party.ready) < party.count:
                return None

            party.phase = PartyPhase.READY_CHECK
            party.ready_check_started = True
            party.confirmed = [party.initiator_id]
            party.confirm_deadlines = {}
            for uid in party.ready:
                if uid != party.initiator_id:
                    party.confirm_deadlines[uid] = now + window
            return party

    async def confirm(self, party_id: str, user_id: int) -> Party | None:
        """Юзер нажал «Подтверждаю» в фазе чека.

        Возвращает :class:`Party` при реальном изменении, иначе ``None``
        (не в чеке, не кандидат или уже подтвердил).
        """
        async with self._get_lock():
            party = self._active.get(party_id)
            if party is None or party.finalized:
                return None
            if party.phase is not PartyPhase.READY_CHECK:
                return None
            if user_id not in party.ready or user_id in party.confirmed:
                return None

            party.confirm_deadlines.pop(user_id, None)
            party.confirmed.append(user_id)
            return party

    async def tick_ready_check(
        self, party_id: str, *, now: datetime, window: timedelta
    ) -> ReadyCheckTick:
        """Один проход чек-таймера: гасит просроченных, поднимает начинку.

        Алгоритм под общим локом:

        1. Если уже набралось ``count`` подтверждений — ``finished="success"``.
        2. Просроченные кандидаты выбывают из основы в ``not_confirmed``.
        3. Освободившиеся слоты основы (из начинки) получают новое окно.
        4. Если подтверждений хватает — ``finished="success"``.
        5. Если открытых окон не осталось, а состав не полон — заполнять некем,
           ``finished="partial"``.
        """
        async with self._get_lock():
            party = self._active.get(party_id)
            if party is None or party.finalized or party.phase is not PartyPhase.READY_CHECK:
                return ReadyCheckTick(finished=None)

            if len(party.confirmed) >= party.count:
                return ReadyCheckTick(finished="success")

            dropped = [uid for uid, dl in party.confirm_deadlines.items() if dl <= now]
            for uid in dropped:
                del party.confirm_deadlines[uid]
                if uid in party.joined_order:
                    party.joined_order.remove(uid)
                party.not_confirmed.append(uid)

            promoted: list[int] = []
            for uid in party.ready:
                if uid in party.confirmed or uid in party.confirm_deadlines:
                    continue
                party.confirm_deadlines[uid] = now + window
                promoted.append(uid)

            if len(party.confirmed) >= party.count:
                return ReadyCheckTick(changed=True, dropped=dropped, finished="success")

            if not party.confirm_deadlines and len(party.confirmed) < party.count:
                # Все, кого ждали, разрешились, а слоты заполнять некем.
                return ReadyCheckTick(changed=True, dropped=dropped, finished="partial")

            return ReadyCheckTick(
                changed=bool(dropped or promoted), promoted=promoted, dropped=dropped
            )

    async def cancel(self, party_id: str) -> Party | None:
        """Удаляет пати из активных и помечает финализированным (атомарно)."""
        async with self._get_lock():
            party = self._active.pop(party_id, None)
            if party is None:
                return None
            party.finalized = True
            return party

    def get(self, party_id: str) -> Party | None:
        """Достаёт пати по идентификатору (read-only, lock не нужен)."""
        return self._active.get(party_id)

    def list_for_initiator(self, initiator_id: int) -> list[Party]:
        """Все активные пати указанного инициатора (для /party_cancel)."""
        return [p for p in self._active.values() if p.initiator_id == initiator_id]

    def all_active(self) -> list[Party]:
        """Снимок всех активных пати (для cog_unload)."""
        return list(self._active.values())
