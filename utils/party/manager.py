"""In-memory state-менеджер активных пати.

Хранит структуру :class:`Party` для каждого активного сбора. Никаких I/O —
модуль чистый, что упрощает unit-тестирование без Discord/БД.

Семантика: пользователи нажимают кнопки «Готов» / «Не готов» в DM. ``mark_ready``
переносит юзера в ``joined_order`` (и убирает из ``declined_order``, если был),
``mark_declined`` — наоборот. Инициатор стартует в ``joined_order`` автоматически.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


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
        joined_order: ID юзеров в порядке нажатия «Готов» (FIFO для ready/bench).
        declined_order: ID юзеров, нажавших «Не готов».
        dm_messages: ``user_id -> discord.Message`` — DM-сообщение каждого
            юзера (нужно, чтобы синхронно обновлять embed во всех личках).
        last_press: ``user_id -> момент последнего нажатия`` — для кулдауна
            между «Готов» / «Не готов».
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
    joined_order: list[int] = field(default_factory=list)
    declined_order: list[int] = field(default_factory=list)
    dm_messages: dict[int, discord.Message] = field(default_factory=dict)
    last_press: dict[int, datetime] = field(default_factory=dict)
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


class PartyManager:
    """Коллекция активных пати с лукапом по id."""

    def __init__(self) -> None:
        self._active: dict[str, Party] = {}

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
            joined_order=[initiator_id],
        )
        self._active[party.id] = party
        return party

    def mark_ready(self, party_id: str, user_id: int) -> Party | None:
        """Юзер нажал «Готов».

        Возвращает :class:`Party` если состояние реально изменилось (надо
        перерисовать embed), иначе ``None``. ``None`` также если пати
        не найден или уже закрыт.
        """
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

    def mark_declined(self, party_id: str, user_id: int) -> Party | None:
        """Юзер нажал «Не готов».

        Инициатор НЕ может попасть в declined — у него нет DM с кнопками,
        но на всякий случай отдельно его не пускаем.
        """
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
        if not already_declined:
            party.declined_order.append(user_id)
        return party

    def cancel(self, party_id: str) -> Party | None:
        """Удаляет пати из активных и помечает финализированным."""
        party = self._active.pop(party_id, None)
        if party is None:
            return None
        party.finalized = True
        return party

    def get(self, party_id: str) -> Party | None:
        """Достаёт пати по идентификатору."""
        return self._active.get(party_id)

    def list_for_initiator(self, initiator_id: int) -> list[Party]:
        """Все активные пати указанного инициатора (для /party_cancel)."""
        return [p for p in self._active.values() if p.initiator_id == initiator_id]

    def all_active(self) -> list[Party]:
        """Снимок всех активных пати (для cog_unload)."""
        return list(self._active.values())
