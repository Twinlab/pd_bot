"""In-memory state-менеджер активных пати.

Хранит структуру :class:`Party` для каждого активного сбора и индексы для
быстрого поиска по id публичного embed-сообщения и id личного DM-сообщения.
Никаких I/O — модуль чистый, что упрощает unit-тестирование без Discord/БД.

Семантика реакций: за юзером закрепляется **первый** поставленный эмодзи и
``reaction_count`` — сколько реакций он держит на DM. Дополнительные эмодзи
просто инкрементят счётчик; эмодзи в embed остаётся первоначальным. Юзер
выпадает из списка только когда ``reaction_count`` падает до нуля.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


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
        count: Сколько человек требуется в основной состав.
        comment: Комментарий, переданный в команду /party.
        created_at: Момент создания пати.
        deadline: Момент, в который сбор должен закрыться.
        dm_messages: ``user_id -> dm_message_id`` для адресации реакций.
        reactions: ``user_id -> зарегистрированный (первый поставленный) эмодзи``.
            Юзер считается записавшимся, пока ``reaction_counts[user_id] > 0``.
        reaction_counts: ``user_id -> сколько реакций юзер сейчас держит на DM``.
        joined_order: ID юзеров в порядке первой реакции (FIFO для ready/bench).
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
    dm_messages: dict[int, int] = field(default_factory=dict)
    reactions: dict[int, str] = field(default_factory=dict)
    reaction_counts: dict[int, int] = field(default_factory=dict)
    joined_order: list[int] = field(default_factory=list)
    finalized: bool = False

    @property
    def ready(self) -> list[int]:
        """ID юзеров, попавших в основной состав (первые ``count`` в FIFO)."""
        return self.joined_order[: self.count]

    @property
    def bench(self) -> list[int]:
        """ID юзеров в начинке (всё, что выше ``count``)."""
        return self.joined_order[self.count :]

    def display_emoji(self, user_id: int, *, initiator_emoji: str) -> str:
        """Возвращает эмодзи для отображения у юзера в embed.

        У инициатора всегда зафиксированный ``initiator_emoji``, у остальных —
        первый поставленный (зарегистрированный) эмодзи.
        """
        if user_id == self.initiator_id:
            return initiator_emoji
        return self.reactions.get(user_id, initiator_emoji)


class PartyManager:
    """Коллекция активных пати + быстрые индексы для listener'ов реакций."""

    def __init__(self) -> None:
        self._active: dict[str, Party] = {}
        self._by_dm_msg: dict[int, Party] = {}
        self._by_public_msg: dict[int, Party] = {}

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
        """Создаёт новую :class:`Party`, регистрирует её во всех индексах.

        Инициатор сразу попадает в ``joined_order`` (auto-ready), но без записи
        в ``reactions`` — у него отдельный ``initiator_emoji`` при отображении.
        """
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
        self._by_public_msg[public_message_id] = party
        return party

    def register_dm(self, party_id: str, user_id: int, dm_message_id: int) -> None:
        """Связывает DM-сообщение с пати, чтобы listener мог его быстро найти."""
        party = self._active.get(party_id)
        if party is None:
            return
        party.dm_messages[user_id] = dm_message_id
        self._by_dm_msg[dm_message_id] = party

    def add_reaction(self, dm_message_id: int, user_id: int, emoji: str) -> Party | None:
        """Учитывает постановку реакции на DM.

        Если у юзера ещё нет зарегистрированной реакции — фиксируем первый эмодзи
        и возвращаем :class:`Party` для перерисовки. Если юзер уже записан и
        просто ставит вторую реакцию — увеличиваем счётчик и возвращаем ``None``
        (embed обновлять незачем).

        Возвращает ``None`` также если сообщение не относится ни к одному
        активному сбору или сбор уже финализирован.
        """
        party = self._by_dm_msg.get(dm_message_id)
        if party is None or party.finalized:
            return None
        if user_id in party.reactions:
            party.reaction_counts[user_id] = party.reaction_counts.get(user_id, 0) + 1
            return None
        party.reactions[user_id] = emoji
        party.reaction_counts[user_id] = 1
        if user_id not in party.joined_order:
            party.joined_order.append(user_id)
        return party

    def remove_reaction(self, dm_message_id: int, user_id: int, emoji: str) -> Party | None:
        """Учитывает снятие реакции с DM.

        Эмодзи, который снимают, не важен — мы только декрементим счётчик. Если
        у юзера остались другие реакции — возвращаем ``None`` (embed без
        изменений, зарегистрированный эмодзи прежний). Если счётчик упал до нуля
        — выбиваем юзера из всех структур и возвращаем :class:`Party`.

        Инициатор не выбивается из ``joined_order`` ни при каких условиях.
        """
        party = self._by_dm_msg.get(dm_message_id)
        if party is None or party.finalized:
            return None
        if user_id not in party.reactions:
            return None
        new_count = max(0, party.reaction_counts.get(user_id, 0) - 1)
        if new_count > 0:
            party.reaction_counts[user_id] = new_count
            return None
        del party.reactions[user_id]
        del party.reaction_counts[user_id]
        if user_id != party.initiator_id and user_id in party.joined_order:
            party.joined_order.remove(user_id)
        return party

    def cancel(self, party_id: str) -> Party | None:
        """Удаляет пати из всех индексов и помечает финализированным."""
        party = self._active.pop(party_id, None)
        if party is None:
            return None
        self._by_public_msg.pop(party.public_message_id, None)
        for dm_msg_id in party.dm_messages.values():
            self._by_dm_msg.pop(dm_msg_id, None)
        party.finalized = True
        return party

    def get(self, party_id: str) -> Party | None:
        """Достаёт пати по идентификатору."""
        return self._active.get(party_id)

    def get_by_dm_message(self, dm_message_id: int) -> Party | None:
        """Достаёт пати по id DM-сообщения (быстрый путь для listener'ов)."""
        return self._by_dm_msg.get(dm_message_id)

    def get_by_public_message(self, public_message_id: int) -> Party | None:
        """Достаёт пати по id публичного embed-сообщения."""
        return self._by_public_msg.get(public_message_id)

    def list_for_initiator(self, initiator_id: int) -> list[Party]:
        """Все активные пати указанного инициатора (для /party_cancel)."""
        return [p for p in self._active.values() if p.initiator_id == initiator_id]

    def all_active(self) -> list[Party]:
        """Снимок всех активных пати (для cog_unload)."""
        return list(self._active.values())
