"""Тесты для модуля управления привязками эмодзи к ролям Discord."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List, Optional, Tuple

from utils.role_reaction_data_manager import RoleReactionDataManager
from utils.models import RoleReaction


@pytest.fixture
def manager():
    """Создает экземпляр RoleReactionDataManager."""
    return RoleReactionDataManager()


class TestRoleReactionDataManagerInit:
    """Тесты инициализации RoleReactionDataManager."""

    def test_init(self):
        """Тест инициализации."""
        manager = RoleReactionDataManager()
        assert manager is not None


class TestGetMessageInfo:
    """Тесты метода get_message_info."""

    @pytest.mark.asyncio
    async def test_get_message_info_success(self, manager):
        """Тест успешного получения информации о сообщении."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_reaction = MagicMock(channel_id=123456, message_id=789012)
            mock_filter.return_value.first = AsyncMock(return_value=mock_reaction)
            
            result = await manager.get_message_info(guild_id=111222333)
            
            assert result == (123456, 789012)
            mock_filter.assert_called_once_with(guild_id=111222333)

    @pytest.mark.asyncio
    async def test_get_message_info_not_found(self, manager):
        """Тест получения информации о сообщении, когда данные не найдены."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_filter.return_value.first = AsyncMock(return_value=None)
            
            result = await manager.get_message_info(guild_id=111222333)
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_message_info_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении информации о сообщении."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_filter.side_effect = Exception("Database error")
            
            result = await manager.get_message_info(guild_id=111222333)
            
            assert result is None


class TestAddRoleReaction:
    """Тесты метода add_role_reaction."""

    @pytest.mark.asyncio
    async def test_add_role_reaction_success(self, manager):
        """Тест успешного добавления привязки роли."""
        with patch("utils.role_reaction_data_manager.RoleReaction.update_or_create", new_callable=AsyncMock) as mock_update_or_create:
            result = await manager.add_role_reaction(
                guild_id=111222333,
                channel_id=123456,
                message_id=789012,
                emoji="🎮",
                role_id=555666777,
                description="Геймер"
            )
            
            assert result is True
            mock_update_or_create.assert_called_once_with(
                guild_id=111222333,
                message_id=789012,
                emoji="🎮",
                defaults={
                    "channel_id": 123456,
                    "role_id": 555666777,
                    "description": "Геймер",
                },
            )

    @pytest.mark.asyncio
    async def test_add_role_reaction_database_error(self, manager):
        """Тест обработки ошибки базы данных при добавлении привязки роли."""
        with patch("utils.role_reaction_data_manager.RoleReaction.update_or_create", new_callable=AsyncMock) as mock_update_or_create:
            mock_update_or_create.side_effect = Exception("Database error")
            
            result = await manager.add_role_reaction(
                guild_id=111222333,
                channel_id=123456,
                message_id=789012,
                emoji="🎮",
                role_id=555666777,
                description="Геймер"
            )
            
            assert result is False


class TestRemoveRoleReaction:
    """Тесты метода remove_role_reaction."""

    @pytest.mark.asyncio
    async def test_remove_role_reaction_success(self, manager):
        """Тест успешного удаления привязки роли."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_delete = AsyncMock(return_value=1)
            mock_filter.return_value.delete = mock_delete
            
            result = await manager.remove_role_reaction(guild_id=111222333, emoji="🎮")
            
            assert result is True
            mock_filter.assert_called_once_with(guild_id=111222333, emoji="🎮")
            mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_role_reaction_not_found(self, manager):
        """Тест удаления несуществующей привязки роли."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_delete = AsyncMock(return_value=0)
            mock_filter.return_value.delete = mock_delete
            
            result = await manager.remove_role_reaction(guild_id=111222333, emoji="🎮")
            
            assert result is False

    @pytest.mark.asyncio
    async def test_remove_role_reaction_database_error(self, manager):
        """Тест обработки ошибки базы данных при удалении привязки роли."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_filter.side_effect = Exception("Database error")
            
            result = await manager.remove_role_reaction(guild_id=111222333, emoji="🎮")
            
            assert result is False


class TestGetAllRoleReactions:
    """Тесты метода get_all_role_reactions."""

    @pytest.mark.asyncio
    async def test_get_all_role_reactions_success(self, manager):
        """Тест успешного получения всех привязок ролей."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_reaction1 = MagicMock(
                channel_id=123456,
                message_id=789012,
                emoji="🎮",
                role_id=555666777,
                description="Геймер"
            )
            mock_reaction2 = MagicMock(
                channel_id=123456,
                message_id=789012,
                emoji="🎵",
                role_id=888999000,
                description="Музыкант"
            )
            
            # Имитируем awaitable результат filter().order_by()
            mock_order_by = AsyncMock(return_value=[mock_reaction1, mock_reaction2])
            
            mock_filter.return_value.order_by = mock_order_by
            
            result = await manager.get_all_role_reactions(guild_id=111222333)
            
            expected = [
                {
                    "channel_id": 123456,
                    "message_id": 789012,
                    "emoji": "🎮",
                    "role_id": 555666777,
                    "description": "Геймер"
                },
                {
                    "channel_id": 123456,
                    "message_id": 789012,
                    "emoji": "🎵",
                    "role_id": 888999000,
                    "description": "Музыкант"
                }
            ]
            assert result == expected
            mock_filter.assert_called_once_with(guild_id=111222333)

    @pytest.mark.asyncio
    async def test_get_all_role_reactions_empty_result(self, manager):
        """Тест получения пустого списка привязок ролей."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_order_by = AsyncMock(return_value=[])
            mock_filter.return_value.order_by = mock_order_by
            
            result = await manager.get_all_role_reactions(guild_id=111222333)
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_all_role_reactions_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении всех привязок ролей."""
        with patch("utils.role_reaction_data_manager.RoleReaction.filter") as mock_filter:
            mock_filter.side_effect = Exception("Database error")
            
            result = await manager.get_all_role_reactions(guild_id=111222333)
            
            assert result == []


class TestGetRoleByEmoji:
    """Тесты метода get_role_by_emoji."""

    @pytest.mark.asyncio
    async def test_get_role_by_emoji_success(self, manager):
        """Тест успешного получения роли по эмодзи."""
        with patch("utils.role_reaction_data_manager.RoleReaction.get_or_none", new_callable=AsyncMock) as mock_get_or_none:
            mock_reaction = MagicMock(role_id=555666777)
            mock_get_or_none.return_value = mock_reaction
            
            result = await manager.get_role_by_emoji(guild_id=111222333, emoji="🎮")
            
            assert result == 555666777
            mock_get_or_none.assert_called_once_with(guild_id=111222333, emoji="🎮")

    @pytest.mark.asyncio
    async def test_get_role_by_emoji_not_found(self, manager):
        """Тест получения роли по эмодзи, когда привязка не найдена."""
        with patch("utils.role_reaction_data_manager.RoleReaction.get_or_none", new_callable=AsyncMock) as mock_get_or_none:
            mock_get_or_none.return_value = None
            
            result = await manager.get_role_by_emoji(guild_id=111222333, emoji="🎮")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_role_by_emoji_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении роли по эмодзи."""
        with patch("utils.role_reaction_data_manager.RoleReaction.get_or_none", new_callable=AsyncMock) as mock_get_or_none:
            mock_get_or_none.side_effect = Exception("Database error")
            
            result = await manager.get_role_by_emoji(guild_id=111222333, emoji="🎮")
            
            assert result is None