"""Тесты для PartyDataManager (blacklist команды /party)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.party.data_manager import PartyDataManager


@pytest.fixture
def manager() -> PartyDataManager:
    """Новый экземпляр data-manager."""
    return PartyDataManager()


class TestAddBlock:
    """Тесты add_block."""

    @pytest.mark.asyncio
    async def test_success(self, manager: PartyDataManager) -> None:
        """Успешная блокировка возвращает True и зовёт update_or_create."""
        with patch(
            "utils.party.data_manager.PartyBlock.update_or_create",
            new_callable=AsyncMock,
        ) as mock_upsert:
            result = await manager.add_block(user_id=1, blocked_by=2, reason="спам")

            assert result is True
            mock_upsert.assert_awaited_once_with(
                user_id=1,
                defaults={"blocked_by": 2, "reason": "спам"},
            )

    @pytest.mark.asyncio
    async def test_db_error_returns_false(self, manager: PartyDataManager) -> None:
        """Любое исключение из ORM проглатывается и возвращается False."""
        with patch(
            "utils.party.data_manager.PartyBlock.update_or_create",
            new_callable=AsyncMock,
        ) as mock_upsert:
            mock_upsert.side_effect = RuntimeError("db down")
            assert await manager.add_block(user_id=1, blocked_by=2) is False


class TestRemoveBlock:
    """Тесты remove_block."""

    @pytest.mark.asyncio
    async def test_success(self, manager: PartyDataManager) -> None:
        """Удалена 1 запись → True."""
        with patch("utils.party.data_manager.PartyBlock.filter") as mock_filter:
            mock_filter.return_value.delete = AsyncMock(return_value=1)
            assert await manager.remove_block(user_id=1) is True
            mock_filter.assert_called_once_with(user_id=1)

    @pytest.mark.asyncio
    async def test_not_found(self, manager: PartyDataManager) -> None:
        """Запись не найдена → False, ошибки нет."""
        with patch("utils.party.data_manager.PartyBlock.filter") as mock_filter:
            mock_filter.return_value.delete = AsyncMock(return_value=0)
            assert await manager.remove_block(user_id=1) is False

    @pytest.mark.asyncio
    async def test_db_error_returns_false(self, manager: PartyDataManager) -> None:
        """Исключение из ORM → False."""
        with patch("utils.party.data_manager.PartyBlock.filter") as mock_filter:
            mock_filter.side_effect = RuntimeError("db down")
            assert await manager.remove_block(user_id=1) is False


class TestIsBlocked:
    """Тесты is_blocked."""

    @pytest.mark.asyncio
    async def test_true(self, manager: PartyDataManager) -> None:
        """exists() вернул True → результат True."""
        with patch("utils.party.data_manager.PartyBlock.filter") as mock_filter:
            mock_filter.return_value.exists = AsyncMock(return_value=True)
            assert await manager.is_blocked(user_id=1) is True

    @pytest.mark.asyncio
    async def test_false(self, manager: PartyDataManager) -> None:
        """exists() вернул False → результат False."""
        with patch("utils.party.data_manager.PartyBlock.filter") as mock_filter:
            mock_filter.return_value.exists = AsyncMock(return_value=False)
            assert await manager.is_blocked(user_id=1) is False

    @pytest.mark.asyncio
    async def test_db_error_returns_false(self, manager: PartyDataManager) -> None:
        """ORM упал — функция не должна валить команду /party."""
        with patch("utils.party.data_manager.PartyBlock.filter") as mock_filter:
            mock_filter.side_effect = RuntimeError("db down")
            assert await manager.is_blocked(user_id=1) is False


class TestListBlocks:
    """Тесты list_blocks."""

    @pytest.mark.asyncio
    async def test_returns_records(self, manager: PartyDataManager) -> None:
        """Список из БД маппится в словари с нужными ключами."""
        row = MagicMock()
        row.user_id = 1
        row.blocked_by = 2
        row.reason = "спам"
        row.created_at = "2025-01-01"
        with patch("utils.party.data_manager.PartyBlock.all") as mock_all:
            mock_all.return_value.order_by = AsyncMock(return_value=[row])
            result = await manager.list_blocks()

            assert result == [
                {
                    "user_id": 1,
                    "blocked_by": 2,
                    "reason": "спам",
                    "created_at": "2025-01-01",
                }
            ]

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self, manager: PartyDataManager) -> None:
        """Исключение → пустой список."""
        with patch("utils.party.data_manager.PartyBlock.all") as mock_all:
            mock_all.side_effect = RuntimeError("db down")
            assert await manager.list_blocks() == []
