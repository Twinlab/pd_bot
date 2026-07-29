"""Тесты для TopReactionsDataManager."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tortoise import Tortoise

from utils.models import MessageReactor, ReactedMessage
from utils.time_utils import MOSCOW_TZ
from utils.top_reactions_data_manager import (
    LeaderboardEntry,
    TopReactionsDataManager,
    resolve_period_range,
)


@pytest.fixture
def manager():
    """Экземпляр менеджера с дефолтным content_preview_length."""
    return TopReactionsDataManager(content_preview_length=200)


class TestTruncate:
    """Тесты внутреннего метода обрезки текста."""

    def test_truncate_short_text(self, manager):
        assert manager._truncate("hello", 10) == "hello"

    def test_truncate_long_text(self, manager):
        result = manager._truncate("a" * 50, 10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_truncate_exact_length(self, manager):
        text = "a" * 10
        assert manager._truncate(text, 10) == text


class TestUpsertMessage:
    """Тесты upsert_message."""

    @pytest.mark.asyncio
    async def test_upsert_message_success(self, manager):
        with patch(
            "utils.top_reactions_data_manager.ReactedMessage.update_or_create",
            new_callable=AsyncMock,
        ) as mock_uoc:
            mock_uoc.return_value = (MagicMock(), True)

            await manager.upsert_message(
                message_id=1,
                channel_id=2,
                author_id=3,
                content="hello world",
                jump_url="https://discord.com/x/1",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
            )

            mock_uoc.assert_called_once()
            kwargs = mock_uoc.call_args.kwargs
            assert kwargs["message_id"] == 1
            assert kwargs["defaults"]["author_id"] == 3
            assert kwargs["defaults"]["content"] == "hello world"
            assert kwargs["defaults"]["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_upsert_message_truncates_long_content(self, manager):
        long_content = "x" * 500
        with patch(
            "utils.top_reactions_data_manager.ReactedMessage.update_or_create",
            new_callable=AsyncMock,
        ) as mock_uoc:
            mock_uoc.return_value = (MagicMock(), True)

            await manager.upsert_message(
                message_id=1,
                channel_id=2,
                author_id=3,
                content=long_content,
                jump_url="https://x",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
            )

            saved_content = mock_uoc.call_args.kwargs["defaults"]["content"]
            assert len(saved_content) == 200
            assert saved_content.endswith("…")

    @pytest.mark.asyncio
    async def test_upsert_message_handles_db_error(self, manager):
        with patch(
            "utils.top_reactions_data_manager.ReactedMessage.update_or_create",
            new_callable=AsyncMock,
        ) as mock_uoc:
            mock_uoc.side_effect = Exception("DB error")
            # Не должно бросить — ошибки логируются и съедаются
            await manager.upsert_message(
                message_id=1,
                channel_id=2,
                author_id=3,
                content="x",
                jump_url="x",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
            )


class TestAddReactor:
    """Тесты add_reactor."""

    @pytest.mark.asyncio
    async def test_add_reactor_new(self, manager):
        with patch(
            "utils.top_reactions_data_manager.MessageReactor.get_or_create",
            new_callable=AsyncMock,
        ) as mock_goc:
            mock_goc.return_value = (MagicMock(), True)
            result = await manager.add_reactor(message_id=1, user_id=2, emoji="👍")
            assert result is True
            mock_goc.assert_called_once_with(message_id=1, user_id=2, emoji="👍")

    @pytest.mark.asyncio
    async def test_add_reactor_already_exists(self, manager):
        with patch(
            "utils.top_reactions_data_manager.MessageReactor.get_or_create",
            new_callable=AsyncMock,
        ) as mock_goc:
            mock_goc.return_value = (MagicMock(), False)
            result = await manager.add_reactor(message_id=1, user_id=2, emoji="👍")
            assert result is False

    @pytest.mark.asyncio
    async def test_add_reactor_handles_error(self, manager):
        with patch(
            "utils.top_reactions_data_manager.MessageReactor.get_or_create",
            new_callable=AsyncMock,
        ) as mock_goc:
            mock_goc.side_effect = Exception("DB error")
            result = await manager.add_reactor(message_id=1, user_id=2, emoji="👍")
            assert result is False


class TestRemoveReactor:
    """Тесты remove_reactor."""

    @pytest.mark.asyncio
    async def test_remove_reactor_found(self, manager):
        with patch("utils.top_reactions_data_manager.MessageReactor.filter") as mock_filter:
            mock_filter.return_value.delete = AsyncMock(return_value=1)
            result = await manager.remove_reactor(message_id=1, user_id=2, emoji="👍")
            assert result is True

    @pytest.mark.asyncio
    async def test_remove_reactor_not_found(self, manager):
        with patch("utils.top_reactions_data_manager.MessageReactor.filter") as mock_filter:
            mock_filter.return_value.delete = AsyncMock(return_value=0)
            result = await manager.remove_reactor(message_id=1, user_id=2, emoji="👍")
            assert result is False


class TestRemoveAllReactors:
    """Тесты remove_all_reactors_for_message."""

    @pytest.mark.asyncio
    async def test_remove_all(self, manager):
        with patch("utils.top_reactions_data_manager.MessageReactor.filter") as mock_filter:
            mock_filter.return_value.delete = AsyncMock(return_value=5)
            count = await manager.remove_all_reactors_for_message(123)
            assert count == 5
            mock_filter.assert_called_once_with(message_id=123)


class TestRemoveEmojiForMessage:
    """Тесты remove_emoji_for_message."""

    @pytest.mark.asyncio
    async def test_remove_emoji(self, manager):
        with patch("utils.top_reactions_data_manager.MessageReactor.filter") as mock_filter:
            mock_filter.return_value.delete = AsyncMock(return_value=3)
            count = await manager.remove_emoji_for_message(123, "👍")
            assert count == 3
            mock_filter.assert_called_once_with(message_id=123, emoji="👍")


class TestMessageExists:
    """Тесты message_exists."""

    @pytest.mark.asyncio
    async def test_exists_true(self, manager):
        with patch("utils.top_reactions_data_manager.ReactedMessage.filter") as mock_filter:
            mock_filter.return_value.exists = AsyncMock(return_value=True)
            assert await manager.message_exists(1) is True

    @pytest.mark.asyncio
    async def test_exists_false(self, manager):
        with patch("utils.top_reactions_data_manager.ReactedMessage.filter") as mock_filter:
            mock_filter.return_value.exists = AsyncMock(return_value=False)
            assert await manager.message_exists(1) is False


class TestMarkDeleted:
    """Тесты mark_deleted."""

    @pytest.mark.asyncio
    async def test_mark_deleted(self, manager):
        with patch("utils.top_reactions_data_manager.ReactedMessage.filter") as mock_filter:
            mock_filter.return_value.update = AsyncMock(return_value=1)
            await manager.mark_deleted(1)
            mock_filter.assert_called_once_with(message_id=1)
            mock_filter.return_value.update.assert_called_once_with(is_deleted=True)


class TestImportHistorical:
    """Тесты import_historical_message."""

    @pytest.mark.asyncio
    async def test_import_new_message(self, manager):
        with (
            patch(
                "utils.top_reactions_data_manager.ReactedMessage.get_or_none",
                new_callable=AsyncMock,
            ) as mock_gon,
            patch(
                "utils.top_reactions_data_manager.ReactedMessage.create",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_gon.return_value = None
            result = await manager.import_historical_message(
                message_id=1,
                channel_id=2,
                author_id=3,
                content="x",
                jump_url="https://x",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reaction_count=10,
            )
            assert result is True
            mock_create.assert_called_once()
            kwargs = mock_create.call_args.kwargs
            assert kwargs["historical_reaction_count"] == 10

    @pytest.mark.asyncio
    async def test_import_existing_no_overwrite(self, manager):
        existing = MagicMock()
        existing.historical_reaction_count = 5
        existing.save = AsyncMock()
        with patch(
            "utils.top_reactions_data_manager.ReactedMessage.get_or_none",
            new_callable=AsyncMock,
        ) as mock_gon:
            mock_gon.return_value = existing
            result = await manager.import_historical_message(
                message_id=1,
                channel_id=2,
                author_id=3,
                content="x",
                jump_url="https://x",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reaction_count=10,
            )
            assert result is False
            existing.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_existing_with_null_count_no_live_data(self, manager):
        """Если historical_count=None и live данных нет — обновляем."""
        existing = MagicMock()
        existing.historical_reaction_count = None
        existing.save = AsyncMock()
        with (
            patch(
                "utils.top_reactions_data_manager.ReactedMessage.get_or_none",
                new_callable=AsyncMock,
            ) as mock_gon,
            patch("utils.top_reactions_data_manager.MessageReactor.filter") as mock_mr_filter,
        ):
            mock_gon.return_value = existing
            mock_mr_filter.return_value.exists = AsyncMock(return_value=False)

            result = await manager.import_historical_message(
                message_id=1,
                channel_id=2,
                author_id=3,
                content="x",
                jump_url="https://x",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reaction_count=10,
            )
            assert result is False  # Запись не создана, только обновлена
            assert existing.historical_reaction_count == 10
            existing.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_existing_with_live_data_keeps_live(self, manager):
        """Если historical_count=None НО есть live данные — не трогаем."""
        existing = MagicMock()
        existing.historical_reaction_count = None
        existing.save = AsyncMock()
        with (
            patch(
                "utils.top_reactions_data_manager.ReactedMessage.get_or_none",
                new_callable=AsyncMock,
            ) as mock_gon,
            patch("utils.top_reactions_data_manager.MessageReactor.filter") as mock_mr_filter,
        ):
            mock_gon.return_value = existing
            mock_mr_filter.return_value.exists = AsyncMock(return_value=True)  # Есть live

            await manager.import_historical_message(
                message_id=1,
                channel_id=2,
                author_id=3,
                content="x",
                jump_url="https://x",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reaction_count=10,
            )
            existing.save.assert_not_called()


class TestLeaderboardEntry:
    """Базовые тесты dataclass."""

    def test_dataclass_immutable(self):
        entry = LeaderboardEntry(
            message_id=1,
            channel_id=2,
            author_id=3,
            content="x",
            jump_url="https://x",
            posted_at=datetime(2024, 1, 1, tzinfo=UTC),
            reactor_count=5,
            is_historical=False,
        )
        with pytest.raises(AttributeError):
            entry.reactor_count = 10  # frozen dataclass


@pytest.fixture
async def db() -> AsyncIterator[None]:
    """In-memory SQLite через Tortoise — для интеграционных тестов get_leaderboard."""
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["utils.models"]},
        use_tz=False,
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


class TestGetLeaderboard:
    """Интеграционные тесты get_leaderboard на реальной in-memory SQLite.

    Регрессия: ранее в order_by передавался RawSQL-объект, что вызывало
    `TypeError: Field' object is not subscriptable` из pypika и приводило к
    пустой выдаче.
    """

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_messages(self, db, manager):
        result = await manager.get_leaderboard("month", limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_live_messages_sorted_by_reactor_count(self, db, manager):
        now = datetime.now(UTC)
        # msg1 — 1 реактор, msg2 — 3 реактора (даже с дублирующимся эмодзи у юзера 10)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="first",
            jump_url="https://discord.com/x/1",
            posted_at=now,
        )
        await manager.upsert_message(
            message_id=2,
            channel_id=100,
            author_id=201,
            content="second",
            jump_url="https://discord.com/x/2",
            posted_at=now,
        )
        await manager.add_reactor(message_id=1, user_id=10, emoji="👍")
        await manager.add_reactor(message_id=2, user_id=10, emoji="👍")
        await manager.add_reactor(message_id=2, user_id=10, emoji="🔥")  # тот же юзер
        await manager.add_reactor(message_id=2, user_id=11, emoji="👍")
        await manager.add_reactor(message_id=2, user_id=12, emoji="👍")

        result = await manager.get_leaderboard("month", limit=10)
        assert len(result) == 2
        assert result[0].message_id == 2
        assert result[0].reactor_count == 3  # уникальных юзеров, не реакций
        assert result[0].is_historical is False
        assert result[1].message_id == 1
        assert result[1].reactor_count == 1

    @pytest.mark.asyncio
    async def test_historical_fallback_when_no_live(self, db, manager):
        now = datetime.now(UTC)
        await ReactedMessage.create(
            message_id=42,
            channel_id=100,
            author_id=200,
            content="old",
            jump_url="https://x/42",
            posted_at=now,
            historical_reaction_count=7,
        )
        result = await manager.get_leaderboard("month", limit=10)
        assert len(result) == 1
        assert result[0].reactor_count == 7
        assert result[0].is_historical is True

    @pytest.mark.asyncio
    async def test_filters_messages_by_author(self, db, manager):
        now = datetime.now(UTC)
        for message_id, author_id in ((1, 200), (2, 201)):
            await manager.upsert_message(
                message_id=message_id,
                channel_id=100,
                author_id=author_id,
                content=str(author_id),
                jump_url=f"https://discord.com/x/{message_id}",
                posted_at=now,
            )
            await manager.add_reactor(message_id=message_id, user_id=10, emoji="👍")

        result = await manager.get_leaderboard(
            "month",
            limit=10,
            author_id=200,
        )

        assert [entry.author_id for entry in result] == [200]

    @pytest.mark.asyncio
    async def test_live_wins_over_historical_for_same_message(self, db, manager):
        now = datetime.now(UTC)
        await ReactedMessage.create(
            message_id=42,
            channel_id=100,
            author_id=200,
            content="mixed",
            jump_url="https://x/42",
            posted_at=now,
            historical_reaction_count=7,
        )
        # один реальный реактор должен победить historical=7 (live > 0 → берём live)
        await manager.add_reactor(message_id=42, user_id=10, emoji="👍")

        result = await manager.get_leaderboard("month", limit=10)
        assert len(result) == 1
        assert result[0].reactor_count == 1
        assert result[0].is_historical is False

    @pytest.mark.asyncio
    async def test_skips_messages_without_any_reactions(self, db, manager):
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="no reactions",
            jump_url="https://x/1",
            posted_at=now,
        )
        result = await manager.get_leaderboard("month", limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_deleted_messages(self, db, manager):
        now = datetime.now(UTC)
        await ReactedMessage.create(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="gone",
            jump_url="https://x/1",
            posted_at=now,
            historical_reaction_count=99,
            is_deleted=True,
        )
        result = await manager.get_leaderboard("all", limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_period_month_filters_out_other_months(self, db, manager):
        now = datetime.now(UTC)
        old = now.replace(year=now.year - 1)
        await ReactedMessage.create(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="last year",
            jump_url="https://x/1",
            posted_at=old,
            historical_reaction_count=50,
        )
        await ReactedMessage.create(
            message_id=2,
            channel_id=100,
            author_id=200,
            content="this month",
            jump_url="https://x/2",
            posted_at=now,
            historical_reaction_count=10,
        )
        result = await manager.get_leaderboard("month", limit=10)
        assert [r.message_id for r in result] == [2]

    @pytest.mark.asyncio
    async def test_excluded_message_ids_skips_them(self, db, manager):
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="role-reactions",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.upsert_message(
            message_id=2,
            channel_id=100,
            author_id=201,
            content="normal",
            jump_url="https://x/2",
            posted_at=now,
        )
        await manager.add_reactor(message_id=1, user_id=10, emoji="👍")
        await manager.add_reactor(message_id=1, user_id=11, emoji="👍")
        await manager.add_reactor(message_id=2, user_id=12, emoji="👍")

        result = await manager.get_leaderboard("month", limit=10, excluded_message_ids={1})
        assert [r.message_id for r in result] == [2]

    @pytest.mark.asyncio
    async def test_excluded_message_ids_none_or_empty_is_noop(self, db, manager):
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="x",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.add_reactor(message_id=1, user_id=10, emoji="👍")

        assert len(await manager.get_leaderboard("month", limit=10)) == 1
        assert len(await manager.get_leaderboard("month", limit=10, excluded_message_ids=None)) == 1
        assert (
            len(await manager.get_leaderboard("month", limit=10, excluded_message_ids=set())) == 1
        )

    @pytest.mark.asyncio
    async def test_remove_reactor_drops_from_leaderboard(self, db, manager):
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="x",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.add_reactor(message_id=1, user_id=10, emoji="👍")
        assert (await manager.get_leaderboard("month", limit=10))[0].reactor_count == 1

        await manager.remove_reactor(message_id=1, user_id=10, emoji="👍")
        # без реакторов и без historical — не попадает в выдачу
        assert await manager.get_leaderboard("month", limit=10) == []
        # запись о сообщении при этом остаётся в БД
        assert await MessageReactor.filter(message_id=1).count() == 0
        assert await ReactedMessage.filter(message_id=1).exists()

    @pytest.mark.asyncio
    async def test_excluded_user_ids_drops_bot_authors_and_reactors(self, db, manager):
        """excluded_user_ids убирает сообщения ботов и не считает реакции ботов."""
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="человек",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.upsert_message(
            message_id=2,
            channel_id=100,
            author_id=999,  # бот-автор
            content="бот",
            jump_url="https://x/2",
            posted_at=now,
        )
        # На сообщении человека реагируют живой юзер и бот.
        await manager.add_reactor(message_id=1, user_id=10, emoji="👍")
        await manager.add_reactor(message_id=1, user_id=999, emoji="🔥")
        await manager.add_reactor(message_id=2, user_id=10, emoji="👍")

        result = await manager.get_leaderboard("month", limit=10, excluded_user_ids={999})

        assert [r.message_id for r in result] == [1]  # сообщение бота отсеяно
        assert result[0].reactor_count == 1  # реакция бота не учтена

    @pytest.mark.asyncio
    async def test_explicit_year_month_overrides_period(self, db, manager):
        """Если переданы year+month — фильтр идёт по этому конкретному месяцу,
        period фактически игнорируется."""
        await ReactedMessage.create(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="march 2024",
            jump_url="https://x/1",
            posted_at=datetime(2024, 3, 15, tzinfo=UTC),
            historical_reaction_count=10,
        )
        await ReactedMessage.create(
            message_id=2,
            channel_id=100,
            author_id=200,
            content="april 2024",
            jump_url="https://x/2",
            posted_at=datetime(2024, 4, 1, tzinfo=UTC),
            historical_reaction_count=20,
        )

        result = await manager.get_leaderboard("month", limit=10, year=2024, month=3)
        assert [r.message_id for r in result] == [1]

        result = await manager.get_leaderboard("month", limit=10, year=2024, month=4)
        assert [r.message_id for r in result] == [2]

    @pytest.mark.asyncio
    async def test_ignore_self_reactions_excludes_author(self, db, manager):
        """С ignore_self_reactions реакция автора на своё сообщение не считается."""
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="self + others",
            jump_url="https://x/1",
            posted_at=now,
        )
        # автор (200) лайкает сам себя + два других пользователя
        await manager.add_reactor(message_id=1, user_id=200, emoji="👍")
        await manager.add_reactor(message_id=1, user_id=10, emoji="👍")
        await manager.add_reactor(message_id=1, user_id=11, emoji="🔥")

        without = await manager.get_leaderboard("month", limit=10, ignore_self_reactions=False)
        assert without[0].reactor_count == 3

        with_flag = await manager.get_leaderboard("month", limit=10, ignore_self_reactions=True)
        assert with_flag[0].reactor_count == 2

    @pytest.mark.asyncio
    async def test_ignore_self_reactions_drops_self_only_message(self, db, manager):
        """Сообщение, где реактор только сам автор, выпадает из выдачи под флагом."""
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="self only",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.add_reactor(message_id=1, user_id=200, emoji="👍")

        assert len(await manager.get_leaderboard("month", limit=10)) == 1
        assert await manager.get_leaderboard("month", limit=10, ignore_self_reactions=True) == []

    @pytest.mark.asyncio
    async def test_explicit_year_only_takes_whole_year(self, db, manager):
        await ReactedMessage.create(
            message_id=1,
            channel_id=100,
            author_id=200,
            content="2023",
            jump_url="https://x/1",
            posted_at=datetime(2023, 12, 31, tzinfo=UTC),
            historical_reaction_count=5,
        )
        await ReactedMessage.create(
            message_id=2,
            channel_id=100,
            author_id=200,
            content="2024",
            jump_url="https://x/2",
            posted_at=datetime(2024, 1, 1, tzinfo=UTC),
            historical_reaction_count=5,
        )

        result = await manager.get_leaderboard("month", limit=10, year=2024)
        assert [r.message_id for r in result] == [2]


class TestResolvePeriodRange:
    """Юнит-тесты на разрешение (period, year, month) → (start, end)."""

    def test_all_without_explicit_returns_none_none(self):
        start, end = resolve_period_range("all")
        assert start is None
        assert end is None

    def test_month_uses_current_month_when_no_explicit(self):
        now = datetime(2024, 5, 15, 12, 30, tzinfo=UTC)
        start, end = resolve_period_range("month", now=now)
        assert start == datetime(2024, 5, 1, tzinfo=UTC)
        assert end == datetime(2024, 6, 1, tzinfo=UTC)

    def test_month_in_december_wraps_to_next_year(self):
        now = datetime(2024, 12, 5, tzinfo=UTC)
        start, end = resolve_period_range("month", now=now)
        assert start == datetime(2024, 12, 1, tzinfo=UTC)
        assert end == datetime(2025, 1, 1, tzinfo=UTC)

    def test_year_uses_current_year_when_no_explicit(self):
        now = datetime(2024, 5, 15, tzinfo=UTC)
        start, end = resolve_period_range("year", now=now)
        assert start == datetime(2024, 1, 1, tzinfo=UTC)
        assert end == datetime(2025, 1, 1, tzinfo=UTC)

    def test_explicit_year_and_month(self):
        start, end = resolve_period_range("month", year=2023, month=11)
        assert start == datetime(2023, 11, 1, tzinfo=UTC)
        assert end == datetime(2023, 12, 1, tzinfo=UTC)

    def test_explicit_year_and_december_wraps(self):
        start, end = resolve_period_range("month", year=2023, month=12)
        assert start == datetime(2023, 12, 1, tzinfo=UTC)
        assert end == datetime(2024, 1, 1, tzinfo=UTC)

    def test_explicit_year_only(self):
        start, end = resolve_period_range("all", year=2022)
        assert start == datetime(2022, 1, 1, tzinfo=UTC)
        assert end == datetime(2023, 1, 1, tzinfo=UTC)

    def test_explicit_month_only_uses_current_year(self):
        now = datetime(2024, 7, 1, tzinfo=UTC)
        start, end = resolve_period_range("all", now=now, month=2)
        assert start == datetime(2024, 2, 1, tzinfo=UTC)
        assert end == datetime(2024, 3, 1, tzinfo=UTC)

    def test_explicit_month_can_use_moscow_boundaries(self):
        start, end = resolve_period_range(
            "month",
            year=2024,
            month=7,
            timezone=MOSCOW_TZ,
        )
        assert start == datetime(2024, 6, 30, 21, tzinfo=UTC)
        assert end == datetime(2024, 7, 31, 21, tzinfo=UTC)


class TestGetTopAuthors:
    """Интеграционные тесты get_top_authors на in-memory SQLite."""

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, db, manager):
        result = await manager.get_top_authors("all", limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_sums_unique_reactors_across_messages(self, db, manager):
        """Автор A: 3 + 4 = 7 уникальных реакторов на двух сообщениях.
        Автор B: 5 на одном. Топ: B(5), A(7) — нет, A впереди.
        Точнее: A=7, B=5 → A первый."""
        now = datetime.now(UTC)
        # автор A — два сообщения
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="a-1",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.upsert_message(
            message_id=2,
            channel_id=100,
            author_id=10,
            content="a-2",
            jump_url="https://x/2",
            posted_at=now,
        )
        # 3 уникальных реактора на msg1
        for u in (100, 101, 102):
            await manager.add_reactor(message_id=1, user_id=u, emoji="👍")
        # 4 уникальных реактора на msg2
        for u in (200, 201, 202, 203):
            await manager.add_reactor(message_id=2, user_id=u, emoji="🔥")
        # автор B — одно сообщение, 5 реакторов
        await manager.upsert_message(
            message_id=3,
            channel_id=100,
            author_id=20,
            content="b-1",
            jump_url="https://x/3",
            posted_at=now,
        )
        for u in (300, 301, 302, 303, 304):
            await manager.add_reactor(message_id=3, user_id=u, emoji="👍")

        result = await manager.get_top_authors("all", limit=10)
        assert len(result) == 2
        assert result[0].author_id == 10
        assert result[0].total_reactions == 7
        assert result[0].message_count == 2
        assert result[1].author_id == 20
        assert result[1].total_reactions == 5
        assert result[1].message_count == 1

    @pytest.mark.asyncio
    async def test_historical_used_when_no_live(self, db, manager):
        """historical_reaction_count учитывается при отсутствии live-реакций."""
        now = datetime.now(UTC)
        await ReactedMessage.create(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="hist-only",
            jump_url="https://x/1",
            posted_at=now,
            historical_reaction_count=8,
        )
        result = await manager.get_top_authors("all", limit=10)
        assert len(result) == 1
        assert result[0].author_id == 10
        assert result[0].total_reactions == 8
        assert result[0].message_count == 1

    @pytest.mark.asyncio
    async def test_live_wins_over_historical_per_message(self, db, manager):
        """На одном сообщении live перебивает historical."""
        now = datetime.now(UTC)
        await ReactedMessage.create(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="mixed",
            jump_url="https://x/1",
            posted_at=now,
            historical_reaction_count=99,
        )
        await manager.add_reactor(message_id=1, user_id=100, emoji="👍")
        result = await manager.get_top_authors("all", limit=10)
        # historical=99 проигрывает live=1
        assert result[0].total_reactions == 1

    @pytest.mark.asyncio
    async def test_skips_messages_without_any_reactions(self, db, manager):
        """Сообщения без live и без historical не вносят вклад."""
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="silent",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.upsert_message(
            message_id=2,
            channel_id=100,
            author_id=10,
            content="loud",
            jump_url="https://x/2",
            posted_at=now,
        )
        await manager.add_reactor(message_id=2, user_id=100, emoji="👍")

        result = await manager.get_top_authors("all", limit=10)
        assert len(result) == 1
        # message_count = 1, потому что только msg2 даёт вклад
        assert result[0].message_count == 1
        assert result[0].total_reactions == 1

    @pytest.mark.asyncio
    async def test_skips_deleted_messages(self, db, manager):
        now = datetime.now(UTC)
        await ReactedMessage.create(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="gone",
            jump_url="https://x/1",
            posted_at=now,
            historical_reaction_count=50,
            is_deleted=True,
        )
        result = await manager.get_top_authors("all", limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_excluded_message_ids_skipped(self, db, manager):
        now = datetime.now(UTC)
        # role-реакции у автора 10, обычное сообщение у автора 10
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="role-msg",
            jump_url="https://x/1",
            posted_at=now,
        )
        for u in (100, 101, 102):
            await manager.add_reactor(message_id=1, user_id=u, emoji="👍")
        await manager.upsert_message(
            message_id=2,
            channel_id=100,
            author_id=10,
            content="normal",
            jump_url="https://x/2",
            posted_at=now,
        )
        await manager.add_reactor(message_id=2, user_id=200, emoji="🔥")

        result = await manager.get_top_authors("all", limit=10, excluded_message_ids={1})
        assert len(result) == 1
        assert result[0].author_id == 10
        assert result[0].total_reactions == 1  # только msg2
        assert result[0].message_count == 1

    @pytest.mark.asyncio
    async def test_period_filtering_by_explicit_month(self, db, manager):
        await ReactedMessage.create(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="march",
            jump_url="https://x/1",
            posted_at=datetime(2024, 3, 10, tzinfo=UTC),
            historical_reaction_count=4,
        )
        await ReactedMessage.create(
            message_id=2,
            channel_id=100,
            author_id=10,
            content="april",
            jump_url="https://x/2",
            posted_at=datetime(2024, 4, 10, tzinfo=UTC),
            historical_reaction_count=10,
        )

        result = await manager.get_top_authors("month", limit=10, year=2024, month=3)
        assert len(result) == 1
        assert result[0].total_reactions == 4

    @pytest.mark.asyncio
    async def test_ignore_self_reactions_excludes_author(self, db, manager):
        """Под флагом самореакция автора не идёт в его сумму."""
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="self + others",
            jump_url="https://x/1",
            posted_at=now,
        )
        # автор 10 лайкает себя + двух других
        await manager.add_reactor(message_id=1, user_id=10, emoji="👍")
        await manager.add_reactor(message_id=1, user_id=100, emoji="👍")
        await manager.add_reactor(message_id=1, user_id=101, emoji="🔥")

        without = await manager.get_top_authors("all", limit=10, ignore_self_reactions=False)
        assert without[0].total_reactions == 3

        with_flag = await manager.get_top_authors("all", limit=10, ignore_self_reactions=True)
        assert with_flag[0].total_reactions == 2
        assert with_flag[0].message_count == 1

    @pytest.mark.asyncio
    async def test_ignore_self_reactions_drops_self_only_author(self, db, manager):
        """Автор, у которого только самореакции, выпадает из топа под флагом."""
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="self only",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.add_reactor(message_id=1, user_id=10, emoji="👍")

        assert len(await manager.get_top_authors("all", limit=10)) == 1
        assert await manager.get_top_authors("all", limit=10, ignore_self_reactions=True) == []

    @pytest.mark.asyncio
    async def test_excluded_user_ids_drops_bot_authors_and_reactors(self, db, manager):
        """excluded_user_ids убирает авторов-ботов и не считает реакции ботов."""
        now = datetime.now(UTC)
        await manager.upsert_message(
            message_id=1,
            channel_id=100,
            author_id=10,
            content="человек",
            jump_url="https://x/1",
            posted_at=now,
        )
        await manager.upsert_message(
            message_id=2,
            channel_id=100,
            author_id=999,  # бот-автор
            content="бот",
            jump_url="https://x/2",
            posted_at=now,
        )
        await manager.add_reactor(message_id=1, user_id=100, emoji="👍")
        await manager.add_reactor(message_id=1, user_id=999, emoji="🔥")  # реактор-бот
        await manager.add_reactor(message_id=2, user_id=100, emoji="👍")

        result = await manager.get_top_authors("all", limit=10, excluded_user_ids={999})

        assert [r.author_id for r in result] == [10]  # автор-бот отсеян
        assert result[0].total_reactions == 1  # реакция бота не учтена

    @pytest.mark.asyncio
    async def test_limit_respected(self, db, manager):
        now = datetime.now(UTC)
        for author_id in range(1, 6):
            await ReactedMessage.create(
                message_id=author_id,
                channel_id=100,
                author_id=author_id,
                content=f"a{author_id}",
                jump_url=f"https://x/{author_id}",
                posted_at=now,
                historical_reaction_count=author_id,
            )
        result = await manager.get_top_authors("all", limit=3)
        assert len(result) == 3
        # Должны прийти топ-3 по значению (5, 4, 3)
        assert [r.total_reactions for r in result] == [5, 4, 3]
