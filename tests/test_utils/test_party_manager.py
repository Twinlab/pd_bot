"""Тесты для in-memory state-менеджера пати (кнопочная версия)."""

from datetime import UTC, datetime, timedelta

import pytest

from utils.party.manager import Party, PartyManager


@pytest.fixture
def manager() -> PartyManager:
    """Новый пустой менеджер."""
    return PartyManager()


@pytest.fixture
def party(manager: PartyManager) -> Party:
    """Типовое пати: count=3, инициатор=100."""
    now = datetime.now(UTC)
    return manager.create(
        guild_id=1,
        channel_id=10,
        public_message_id=1000,
        role_id=42,
        initiator_id=100,
        count=3,
        comment="идём ранкед",
        created_at=now,
        deadline=now + timedelta(minutes=15),
    )


class TestCreate:
    """Создание пати и стартовое состояние."""

    def test_initiator_in_joined_order(self, party: Party) -> None:
        """Инициатор сразу первый в joined_order."""
        assert party.joined_order == [100]

    def test_no_declined_initially(self, party: Party) -> None:
        """В declined_order пусто на старте."""
        assert party.declined_order == []
        assert party.declined == []

    def test_party_id_is_unique(self, manager: PartyManager) -> None:
        """Каждое пати получает уникальный uuid."""
        now = datetime.now(UTC)
        a = manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1,
            role_id=1,
            initiator_id=1,
            count=1,
            comment="",
            created_at=now,
            deadline=now,
        )
        b = manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=2,
            role_id=1,
            initiator_id=1,
            count=1,
            comment="",
            created_at=now,
            deadline=now,
        )
        assert a.id != b.id


class TestMarkReady:
    """Кнопка «Готов»."""

    def test_first_press_adds_user(self, manager: PartyManager, party: Party) -> None:
        """Первое нажатие «Готов» добавляет юзера в joined_order."""
        result = manager.mark_ready(party.id, user_id=200)
        assert result is party
        assert party.joined_order == [100, 200]

    def test_repeated_press_is_noop(self, manager: PartyManager, party: Party) -> None:
        """Повторное «Готов» от того же юзера ничего не меняет."""
        manager.mark_ready(party.id, user_id=200)
        result = manager.mark_ready(party.id, user_id=200)
        assert result is None
        assert party.joined_order == [100, 200]

    def test_ready_after_declined_moves_user(self, manager: PartyManager, party: Party) -> None:
        """«Готов» после «Не готов» убирает юзера из declined и кладёт в joined."""
        manager.mark_declined(party.id, user_id=200)
        assert 200 in party.declined_order
        result = manager.mark_ready(party.id, user_id=200)
        assert result is party
        assert 200 in party.joined_order
        assert 200 not in party.declined_order

    def test_unknown_party_returns_none(self, manager: PartyManager) -> None:
        """Неизвестный party_id безопасен."""
        assert manager.mark_ready("nope", user_id=200) is None

    def test_finalized_party_ignores(self, manager: PartyManager, party: Party) -> None:
        """После cancel mark_ready не работает."""
        manager.cancel(party.id)
        assert manager.mark_ready(party.id, user_id=200) is None


class TestMarkDeclined:
    """Кнопка «Не готов»."""

    def test_first_press_adds_user(self, manager: PartyManager, party: Party) -> None:
        """Первое нажатие «Не готов» кладёт юзера в declined_order."""
        result = manager.mark_declined(party.id, user_id=200)
        assert result is party
        assert party.declined_order == [200]

    def test_repeated_press_is_noop(self, manager: PartyManager, party: Party) -> None:
        """Повторный «Не готов» ничего не меняет."""
        manager.mark_declined(party.id, user_id=200)
        result = manager.mark_declined(party.id, user_id=200)
        assert result is None

    def test_declined_after_ready_moves_user(self, manager: PartyManager, party: Party) -> None:
        """«Не готов» после «Готов» убирает юзера из joined и кладёт в declined."""
        manager.mark_ready(party.id, user_id=200)
        result = manager.mark_declined(party.id, user_id=200)
        assert result is party
        assert 200 not in party.joined_order
        assert 200 in party.declined_order

    def test_initiator_cannot_decline(self, manager: PartyManager, party: Party) -> None:
        """Инициатор не может попасть в declined (защита от ломки логики)."""
        result = manager.mark_declined(party.id, user_id=100)
        assert result is None
        assert 100 in party.joined_order
        assert party.declined_order == []


class TestReadyAndBench:
    """Свойства ready / bench пересчитываются по count."""

    def test_ready_takes_first_count(self, manager: PartyManager, party: Party) -> None:
        """ready = первые count из joined_order; остальные — bench."""
        for uid in (200, 300, 400, 500):
            manager.mark_ready(party.id, user_id=uid)

        assert party.ready == [100, 200, 300]
        assert party.bench == [400, 500]

    def test_decline_from_ready_promotes_first_bench(
        self, manager: PartyManager, party: Party
    ) -> None:
        """Если готовый нажал «Не готов» — первый из начинки занимает его место."""
        for uid in (200, 300, 400, 500):
            manager.mark_ready(party.id, user_id=uid)

        manager.mark_declined(party.id, user_id=200)

        assert party.ready == [100, 300, 400]
        assert party.bench == [500]
        assert party.declined == [200]


class TestCancel:
    """cancel убирает пати из активных и финализирует."""

    def test_cancel_removes_party(self, manager: PartyManager, party: Party) -> None:
        """После cancel пати недоступен через get."""
        manager.cancel(party.id)
        assert manager.get(party.id) is None
        assert party.finalized is True

    def test_cancel_unknown_returns_none(self, manager: PartyManager) -> None:
        """Cancel на несуществующее party_id безопасен."""
        assert manager.cancel("nope") is None


class TestListForInitiator:
    """Поиск активных пати по инициатору."""

    def test_returns_only_user_parties(self, manager: PartyManager) -> None:
        """В списке только пати указанного инициатора."""
        now = datetime.now(UTC)
        p1 = manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1,
            role_id=1,
            initiator_id=100,
            count=1,
            comment="",
            created_at=now,
            deadline=now,
        )
        manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=2,
            role_id=1,
            initiator_id=200,
            count=1,
            comment="",
            created_at=now,
            deadline=now,
        )
        p3 = manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=3,
            role_id=1,
            initiator_id=100,
            count=1,
            comment="",
            created_at=now,
            deadline=now,
        )
        result = manager.list_for_initiator(100)
        assert {p.id for p in result} == {p1.id, p3.id}


class TestAllActive:
    """Снимок всех активных пати."""

    def test_lists_all(self, manager: PartyManager, party: Party) -> None:
        """all_active возвращает все созданные пати."""
        assert party in manager.all_active()
