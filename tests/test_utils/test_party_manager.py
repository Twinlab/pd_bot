"""Тесты для in-memory state-менеджера пати."""

from datetime import UTC, datetime, timedelta

import pytest

from utils.party.manager import Party, PartyManager


@pytest.fixture
def manager() -> PartyManager:
    """Новый пустой менеджер."""
    return PartyManager()


@pytest.fixture
def party(manager: PartyManager) -> Party:
    """Создаёт типовое пати с 3 нужными участниками; инициатор = 100."""
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
    """Создание пати и проставление инициатора."""

    def test_initiator_in_joined_order(self, party: Party) -> None:
        """Инициатор сразу в joined_order первым."""
        assert party.joined_order == [100]

    def test_initiator_has_no_registered_emoji(self, party: Party) -> None:
        """У инициатора нет записи в reactions — он отображается через initiator_emoji."""
        assert 100 not in party.reactions
        assert 100 not in party.reaction_counts

    def test_party_indexed_by_public_msg(self, manager: PartyManager, party: Party) -> None:
        """Пати находится через индекс по public_message_id."""
        assert manager.get_by_public_message(1000) is party

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


class TestRegisterDM:
    """Регистрация DM-сообщений для адресации реакций."""

    def test_dm_indexed(self, manager: PartyManager, party: Party) -> None:
        """После register_dm пати достаётся по dm_message_id."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        assert manager.get_by_dm_message(2000) is party
        assert party.dm_messages[200] == 2000

    def test_register_unknown_party_is_noop(self, manager: PartyManager) -> None:
        """Регистрация на несуществующее party_id ничего не ломает."""
        manager.register_dm("nope", user_id=200, dm_message_id=2000)
        assert manager.get_by_dm_message(2000) is None


class TestAddReaction:
    """Учёт постановки реакции."""

    def test_first_reaction_registers_user(self, manager: PartyManager, party: Party) -> None:
        """Первая реакция юзера фиксирует эмодзи и добавляет его в joined_order."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        result = manager.add_reaction(2000, user_id=200, emoji="🎮")

        assert result is party
        assert party.joined_order == [100, 200]
        assert party.reactions[200] == "🎮"
        assert party.reaction_counts[200] == 1

    def test_second_emoji_is_ignored_in_display(self, manager: PartyManager, party: Party) -> None:
        """Вторая реакция тем же юзером инкрементит счётчик, но эмодзи не меняет."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        manager.add_reaction(2000, user_id=200, emoji="🎮")
        result = manager.add_reaction(2000, user_id=200, emoji="🎯")

        assert party.reactions[200] == "🎮"
        assert party.reaction_counts[200] == 2
        # вторая реакция не вызывает перерисовку — manager возвращает None
        assert result is None

    def test_unknown_dm_message_returns_none(self, manager: PartyManager, party: Party) -> None:
        """Реакция на чужое сообщение игнорируется."""
        result = manager.add_reaction(99999, user_id=200, emoji="🎮")
        assert result is None
        assert party.joined_order == [100]

    def test_finalized_party_ignores_new_reactions(
        self, manager: PartyManager, party: Party
    ) -> None:
        """После cancel реакции не учитываются."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        manager.cancel(party.id)
        assert manager.add_reaction(2000, user_id=200, emoji="🎮") is None


class TestRemoveReaction:
    """Снятие реакции и FIFO-перерасчёт."""

    def test_removing_only_reaction_drops_user(self, manager: PartyManager, party: Party) -> None:
        """Если у юзера была одна реакция — он выбивается из joined_order."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        manager.add_reaction(2000, user_id=200, emoji="🎮")
        result = manager.remove_reaction(2000, user_id=200, emoji="🎮")

        assert result is party
        assert 200 not in party.reactions
        assert 200 not in party.reaction_counts
        assert party.joined_order == [100]

    def test_removing_one_of_multiple_keeps_user(self, manager: PartyManager, party: Party) -> None:
        """Если у юзера было несколько реакций — он остаётся, эмодзи прежний."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        manager.add_reaction(2000, user_id=200, emoji="🎮")
        manager.add_reaction(2000, user_id=200, emoji="🎯")
        result = manager.remove_reaction(2000, user_id=200, emoji="🎮")

        assert party.reactions[200] == "🎮"
        assert party.reaction_counts[200] == 1
        assert 200 in party.joined_order
        assert result is None  # embed не нужно перерисовывать

    def test_removing_unknown_user_is_noop(self, manager: PartyManager, party: Party) -> None:
        """Снятие реакции у незарегистрированного юзера безопасно."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        result = manager.remove_reaction(2000, user_id=200, emoji="🎮")
        assert result is None

    def test_initiator_not_dropped(self, manager: PartyManager, party: Party) -> None:
        """Инициатор остаётся в joined_order, даже если у него counts → 0."""
        manager.register_dm(party.id, user_id=100, dm_message_id=1001)
        # Эмулируем странный сценарий: инициатор где-то получил DM и среагировал.
        manager.add_reaction(1001, user_id=100, emoji="🎮")
        manager.remove_reaction(1001, user_id=100, emoji="🎮")

        assert 100 in party.joined_order


class TestReadyAndBench:
    """Свойства ready / bench пересчитываются по count."""

    def test_ready_takes_first_count(self, manager: PartyManager, party: Party) -> None:
        """ready = первые count из joined_order; остальные — bench."""
        for uid, msg_id in [(200, 2000), (300, 3000), (400, 4000), (500, 5000)]:
            manager.register_dm(party.id, user_id=uid, dm_message_id=msg_id)
            manager.add_reaction(msg_id, user_id=uid, emoji="✅")

        assert party.ready == [100, 200, 300]
        assert party.bench == [400, 500]

    def test_drop_from_ready_promotes_first_bench(
        self, manager: PartyManager, party: Party
    ) -> None:
        """При выбывании готового первый из начинки занимает его место."""
        for uid, msg_id in [(200, 2000), (300, 3000), (400, 4000), (500, 5000)]:
            manager.register_dm(party.id, user_id=uid, dm_message_id=msg_id)
            manager.add_reaction(msg_id, user_id=uid, emoji="✅")

        manager.remove_reaction(2000, user_id=200, emoji="✅")

        assert party.ready == [100, 300, 400]
        assert party.bench == [500]


class TestDisplayEmoji:
    """display_emoji: инициатор vs обычный юзер."""

    def test_initiator_shows_initiator_emoji(self, party: Party) -> None:
        """У инициатора всегда initiator_emoji, не зависит от его реакций."""
        assert party.display_emoji(100, initiator_emoji="👑") == "👑"

    def test_regular_user_shows_registered_emoji(self, manager: PartyManager, party: Party) -> None:
        """У остальных — зарегистрированный (первый) эмодзи."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        manager.add_reaction(2000, user_id=200, emoji="🎮")
        manager.add_reaction(2000, user_id=200, emoji="🎯")
        assert party.display_emoji(200, initiator_emoji="👑") == "🎮"


class TestCancel:
    """cancel убирает пати из всех индексов и финализирует."""

    def test_cancel_clears_indexes(self, manager: PartyManager, party: Party) -> None:
        """После cancel пати недоступна по любому ключу."""
        manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        manager.cancel(party.id)

        assert manager.get(party.id) is None
        assert manager.get_by_public_message(1000) is None
        assert manager.get_by_dm_message(2000) is None
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
