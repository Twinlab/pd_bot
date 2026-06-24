"""Тесты для in-memory state-менеджера пати (кнопочная версия)."""

from datetime import UTC, datetime, timedelta

import pytest

from utils.party.manager import Party, PartyManager, PartyPhase

WINDOW = timedelta(seconds=120)


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

    async def test_first_press_adds_user(self, manager: PartyManager, party: Party) -> None:
        """Первое нажатие «Готов» добавляет юзера в joined_order."""
        result = await manager.mark_ready(party.id, user_id=200)
        assert result is party
        assert party.joined_order == [100, 200]

    async def test_repeated_press_is_noop(self, manager: PartyManager, party: Party) -> None:
        """Повторное «Готов» от того же юзера ничего не меняет."""
        await manager.mark_ready(party.id, user_id=200)
        result = await manager.mark_ready(party.id, user_id=200)
        assert result is None
        assert party.joined_order == [100, 200]

    async def test_ready_after_declined_moves_user(
        self, manager: PartyManager, party: Party
    ) -> None:
        """«Готов» после «Не готов» убирает юзера из declined и кладёт в joined."""
        await manager.mark_declined(party.id, user_id=200)
        assert 200 in party.declined_order
        result = await manager.mark_ready(party.id, user_id=200)
        assert result is party
        assert 200 in party.joined_order
        assert 200 not in party.declined_order

    async def test_unknown_party_returns_none(self, manager: PartyManager) -> None:
        """Неизвестный party_id безопасен."""
        assert await manager.mark_ready("nope", user_id=200) is None

    async def test_finalized_party_ignores(self, manager: PartyManager, party: Party) -> None:
        """После cancel mark_ready не работает."""
        await manager.cancel(party.id)
        assert await manager.mark_ready(party.id, user_id=200) is None


class TestMarkDeclined:
    """Кнопка «Не готов»."""

    async def test_first_press_adds_user(self, manager: PartyManager, party: Party) -> None:
        """Первое нажатие «Не готов» кладёт юзера в declined_order."""
        result = await manager.mark_declined(party.id, user_id=200)
        assert result is party
        assert party.declined_order == [200]

    async def test_repeated_press_is_noop(self, manager: PartyManager, party: Party) -> None:
        """Повторный «Не готов» ничего не меняет."""
        await manager.mark_declined(party.id, user_id=200)
        result = await manager.mark_declined(party.id, user_id=200)
        assert result is None

    async def test_declined_after_ready_moves_user(
        self, manager: PartyManager, party: Party
    ) -> None:
        """«Не готов» после «Готов» убирает юзера из joined и кладёт в declined."""
        await manager.mark_ready(party.id, user_id=200)
        result = await manager.mark_declined(party.id, user_id=200)
        assert result is party
        assert 200 not in party.joined_order
        assert 200 in party.declined_order

    async def test_initiator_cannot_decline(self, manager: PartyManager, party: Party) -> None:
        """Инициатор не может попасть в declined (защита от ломки логики)."""
        result = await manager.mark_declined(party.id, user_id=100)
        assert result is None
        assert 100 in party.joined_order
        assert party.declined_order == []


class TestReadyAndBench:
    """Свойства ready / bench пересчитываются по count."""

    async def test_ready_takes_first_count(self, manager: PartyManager, party: Party) -> None:
        """ready = первые count из joined_order; остальные — bench."""
        for uid in (200, 300, 400, 500):
            await manager.mark_ready(party.id, user_id=uid)

        assert party.ready == [100, 200, 300]
        assert party.bench == [400, 500]

    async def test_decline_from_ready_promotes_first_bench(
        self, manager: PartyManager, party: Party
    ) -> None:
        """Если готовый нажал «Не готов» — первый из начинки занимает его место."""
        for uid in (200, 300, 400, 500):
            await manager.mark_ready(party.id, user_id=uid)

        await manager.mark_declined(party.id, user_id=200)

        assert party.ready == [100, 300, 400]
        assert party.bench == [500]
        assert party.declined == [200]


class TestCancel:
    """cancel убирает пати из активных и финализирует."""

    async def test_cancel_removes_party(self, manager: PartyManager, party: Party) -> None:
        """После cancel пати недоступен через get."""
        await manager.cancel(party.id)
        assert manager.get(party.id) is None
        assert party.finalized is True

    async def test_cancel_unknown_returns_none(self, manager: PartyManager) -> None:
        """Cancel на несуществующее party_id безопасен."""
        assert await manager.cancel("nope") is None


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


async def _fill_main(manager: PartyManager, party: Party) -> None:
    """Добивает основу до count: инициатор + (count-1) готовых (200, 300, ...)."""
    for i in range(party.count - 1):
        await manager.mark_ready(party.id, user_id=200 + i * 100)


class TestStartReadyCheck:
    """Переход в фазу чека готовности."""

    async def test_starts_when_main_full(self, manager: PartyManager, party: Party) -> None:
        """Чек стартует, инициатор сразу подтверждён, остальным открыт дедлайн."""
        await _fill_main(manager, party)  # 100 (init) + 200, 300 → count=3
        now = datetime.now(UTC)

        result = await manager.start_ready_check(party.id, now=now, window=WINDOW)

        assert result is party
        assert party.phase is PartyPhase.READY_CHECK
        assert party.ready_check_started is True
        assert party.confirmed == [100]
        assert set(party.confirm_deadlines) == {200, 300}

    async def test_returns_none_when_not_full(self, manager: PartyManager, party: Party) -> None:
        """Если основа не набрана — чек не стартует."""
        await manager.mark_ready(party.id, user_id=200)  # только 2 из 3
        result = await manager.start_ready_check(party.id, now=datetime.now(UTC), window=WINDOW)
        assert result is None
        assert party.phase is PartyPhase.COLLECTING

    async def test_double_start_is_noop(self, manager: PartyManager, party: Party) -> None:
        """Повторный старт чека возвращает None."""
        await _fill_main(manager, party)
        now = datetime.now(UTC)
        await manager.start_ready_check(party.id, now=now, window=WINDOW)
        assert await manager.start_ready_check(party.id, now=now, window=WINDOW) is None


class TestConfirm:
    """Кнопка «Подтверждаю»."""

    async def test_confirm_moves_user(self, manager: PartyManager, party: Party) -> None:
        """Подтверждение переносит юзера в confirmed и снимает дедлайн."""
        await _fill_main(manager, party)
        await manager.start_ready_check(party.id, now=datetime.now(UTC), window=WINDOW)

        result = await manager.confirm(party.id, user_id=200)

        assert result is party
        assert 200 in party.confirmed
        assert 200 not in party.confirm_deadlines

    async def test_confirm_twice_is_noop(self, manager: PartyManager, party: Party) -> None:
        """Повторное подтверждение ничего не меняет."""
        await _fill_main(manager, party)
        await manager.start_ready_check(party.id, now=datetime.now(UTC), window=WINDOW)
        await manager.confirm(party.id, user_id=200)
        assert await manager.confirm(party.id, user_id=200) is None

    async def test_confirm_outside_check_is_noop(self, manager: PartyManager, party: Party) -> None:
        """Вне фазы чека подтверждать нельзя."""
        assert await manager.confirm(party.id, user_id=200) is None

    async def test_non_candidate_cannot_confirm(self, manager: PartyManager, party: Party) -> None:
        """Юзер из начинки (не в основе) подтвердить не может."""
        for uid in (200, 300, 400):
            await manager.mark_ready(party.id, user_id=uid)  # 400 — начинка
        await manager.start_ready_check(party.id, now=datetime.now(UTC), window=WINDOW)
        assert await manager.confirm(party.id, user_id=400) is None


class TestTickReadyCheck:
    """Sweep чек-таймера: таймауты, промоут начинки, финалы."""

    async def test_success_when_all_confirmed(self, manager: PartyManager, party: Party) -> None:
        """Когда подтвердили count — finished=success."""
        await _fill_main(manager, party)
        await manager.start_ready_check(party.id, now=datetime.now(UTC), window=WINDOW)
        await manager.confirm(party.id, user_id=200)
        await manager.confirm(party.id, user_id=300)

        tick = await manager.tick_ready_check(party.id, now=datetime.now(UTC), window=WINDOW)
        assert tick.finished == "success"

    async def test_timeout_promotes_bench(self, manager: PartyManager, party: Party) -> None:
        """Просроченный кандидат выбывает, начинка занимает слот и получает окно."""
        for uid in (200, 300, 400):
            await manager.mark_ready(party.id, user_id=uid)  # 400 — начинка
        start = datetime.now(UTC)
        await manager.start_ready_check(party.id, now=start, window=WINDOW)
        await manager.confirm(party.id, user_id=300)  # 300 успел, 200 — нет

        later = start + WINDOW + timedelta(seconds=1)
        tick = await manager.tick_ready_check(party.id, now=later, window=WINDOW)

        assert tick.finished is None
        assert tick.dropped == [200]
        assert 400 in tick.promoted
        assert 200 in party.not_confirmed
        assert 200 not in party.joined_order
        assert party.ready == [100, 300, 400]
        assert 400 in party.confirm_deadlines

    async def test_partial_when_no_bench_left(self, manager: PartyManager, party: Party) -> None:
        """Без начинки и с таймаутом — finished=partial (закрываем частично)."""
        await _fill_main(manager, party)  # 100, 200, 300, без резерва
        start = datetime.now(UTC)
        await manager.start_ready_check(party.id, now=start, window=WINDOW)
        await manager.confirm(party.id, user_id=200)

        later = start + WINDOW + timedelta(seconds=1)
        tick = await manager.tick_ready_check(party.id, now=later, window=WINDOW)

        assert tick.finished == "partial"
        assert party.confirmed == [100, 200]
        assert 300 in party.not_confirmed

    async def test_declined_confirmed_user_leaves(
        self, manager: PartyManager, party: Party
    ) -> None:
        """«Не готов» от подтверждённого убирает его и из confirmed."""
        await _fill_main(manager, party)
        await manager.start_ready_check(party.id, now=datetime.now(UTC), window=WINDOW)
        await manager.confirm(party.id, user_id=200)

        await manager.mark_declined(party.id, user_id=200)

        assert 200 not in party.confirmed
        assert 200 not in party.joined_order
        assert 200 in party.declined_order
