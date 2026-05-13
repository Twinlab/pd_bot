"""Тесты для TopReactionsDataManager."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tortoise import Tortoise

from utils.models import MessageReactor, ReactedMessage
from utils.top_reactions_data_manager import (
    LeaderboardEntry,
    TopReactionsDataManager,
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
