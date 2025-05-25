"""Тесты для модуля управления привязками эмодзи к ролям Discord."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List, Optional, Tuple

from utils.role_reaction_data_manager import RoleReactionDataManager


class TestRoleReactionDataManagerInit:
    """Тесты инициализации RoleReactionDataManager."""

    def test_init_default_path(self):
        """Тест инициализации с путем по умолчанию."""
        manager = RoleReactionDataManager()
        # Проверяем, что путь содержит ожидаемые части
        assert 'bot_data.db' in manager.db_path or 'data' in manager.db_path

    def test_init_custom_path(self):
        """Тест инициализации с пользовательским путем."""
        custom_path = '/custom/path/test.db'
        manager = RoleReactionDataManager(db_path=custom_path)
        assert manager.db_path == custom_path


class TestGetMessageInfo:
    """Тесты метода get_message_info."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр RoleReactionDataManager."""
        return RoleReactionDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_get_message_info_success(self, manager):
        """Тест успешного получения информации о сообщении."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = (123456, 789012)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_message_info(guild_id=111222333)
            
            assert result == (123456, 789012)
            mock_conn.execute.assert_called_once()
            call_args = mock_conn.execute.call_args
            assert "SELECT channel_id, message_id FROM role_reactions" in call_args[0][0]
            assert call_args[0][1] == (111222333,)

    @pytest.mark.asyncio
    async def test_get_message_info_not_found(self, manager):
        """Тест получения информации о сообщении, когда данные не найдены."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_message_info(guild_id=111222333)
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_message_info_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении информации о сообщении."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.role_reaction_data_manager.logger') as mock_logger:
                result = await manager.get_message_info(guild_id=111222333)
                
                assert result is None
                mock_logger.error.assert_called_once()
                assert "Ошибка при получении информации о сообщении" in mock_logger.error.call_args[0][0]


class TestAddRoleReaction:
    """Тесты метода add_role_reaction."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр RoleReactionDataManager."""
        return RoleReactionDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_add_role_reaction_success(self, manager):
        """Тест успешного добавления привязки роли."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.add_role_reaction(
                guild_id=111222333,
                channel_id=123456,
                message_id=789012,
                emoji="🎮",
                role_id=555666777,
                description="Геймер"
            )
            
            assert result is True
            mock_conn.execute.assert_called_once()
            call_args = mock_conn.execute.call_args
            assert "INSERT OR REPLACE INTO role_reactions" in call_args[0][0]
            assert call_args[0][1] == (111222333, 123456, 789012, "🎮", 555666777, "Геймер")
            mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_role_reaction_database_error(self, manager):
        """Тест обработки ошибки базы данных при добавлении привязки роли."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.role_reaction_data_manager.logger') as mock_logger:
                result = await manager.add_role_reaction(
                    guild_id=111222333,
                    channel_id=123456,
                    message_id=789012,
                    emoji="🎮",
                    role_id=555666777,
                    description="Геймер"
                )
                
                assert result is False
                mock_logger.error.assert_called_once()
                assert "Ошибка при добавлении привязки роли" in mock_logger.error.call_args[0][0]


class TestRemoveRoleReaction:
    """Тесты метода remove_role_reaction."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр RoleReactionDataManager."""
        return RoleReactionDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_remove_role_reaction_success(self, manager):
        """Тест успешного удаления привязки роли."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 1
        mock_conn.execute.return_value = mock_cursor
        mock_conn.commit = AsyncMock()
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.remove_role_reaction(guild_id=111222333, emoji="🎮")
            
            assert result is True
            mock_conn.execute.assert_called_once()
            call_args = mock_conn.execute.call_args
            assert "DELETE FROM role_reactions" in call_args[0][0]
            assert call_args[0][1] == (111222333, "🎮")
            mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_role_reaction_not_found(self, manager):
        """Тест удаления несуществующей привязки роли."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 0
        mock_conn.execute.return_value = mock_cursor
        mock_conn.commit = AsyncMock()
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            with patch('utils.role_reaction_data_manager.logger') as mock_logger:
                result = await manager.remove_role_reaction(guild_id=111222333, emoji="🎮")
                
                assert result is False
                mock_logger.warning.assert_called_once()
                assert "Привязка для удаления не найдена" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_remove_role_reaction_database_error(self, manager):
        """Тест обработки ошибки базы данных при удалении привязки роли."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.role_reaction_data_manager.logger') as mock_logger:
                result = await manager.remove_role_reaction(guild_id=111222333, emoji="🎮")
                
                assert result is False
                mock_logger.error.assert_called_once()
                assert "Ошибка при удалении привязки роли" in mock_logger.error.call_args[0][0]


class TestGetAllRoleReactions:
    """Тесты метода get_all_role_reactions."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр RoleReactionDataManager."""
        return RoleReactionDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_get_all_role_reactions_success(self, manager):
        """Тест успешного получения всех привязок ролей."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        
        # Создаем мок строки с доступом по ключам
        mock_row1 = {
            "channel_id": 123456,
            "message_id": 789012,
            "emoji": "🎮",
            "role_id": 555666777,
            "description": "Геймер"
        }
        mock_row2 = {
            "channel_id": 123456,
            "message_id": 789012,
            "emoji": "🎵",
            "role_id": 888999000,
            "description": "Музыкант"
        }
        
        mock_cursor.__aiter__.return_value = [mock_row1, mock_row2]
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_cursor.__aexit__.return_value = None
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            with patch('aiosqlite.Row'):
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
                
                # Проверяем SQL запрос
                mock_conn.execute.assert_called_once()
                call_args = mock_conn.execute.call_args
                assert "SELECT channel_id, message_id, emoji, role_id, description" in call_args[0][0]
                assert call_args[0][1] == (111222333,)

    @pytest.mark.asyncio
    async def test_get_all_role_reactions_empty_result(self, manager):
        """Тест получения пустого списка привязок ролей."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = []
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_cursor.__aexit__.return_value = None
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            with patch('aiosqlite.Row'):
                result = await manager.get_all_role_reactions(guild_id=111222333)
                
                assert result == []

    @pytest.mark.asyncio
    async def test_get_all_role_reactions_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении всех привязок ролей."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.role_reaction_data_manager.logger') as mock_logger:
                result = await manager.get_all_role_reactions(guild_id=111222333)
                
                assert result == []
                mock_logger.error.assert_called_once()
                assert "Ошибка при получении привязок ролей" in mock_logger.error.call_args[0][0]


class TestGetRoleByEmoji:
    """Тесты метода get_role_by_emoji."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр RoleReactionDataManager."""
        return RoleReactionDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_get_role_by_emoji_success(self, manager):
        """Тест успешного получения роли по эмодзи."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = (555666777,)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_role_by_emoji(guild_id=111222333, emoji="🎮")
            
            assert result == 555666777
            mock_conn.execute.assert_called_once()
            call_args = mock_conn.execute.call_args
            assert "SELECT role_id FROM role_reactions" in call_args[0][0]
            assert call_args[0][1] == (111222333, "🎮")

    @pytest.mark.asyncio
    async def test_get_role_by_emoji_not_found(self, manager):
        """Тест получения роли по эмодзи, когда привязка не найдена."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = MagicMock(return_value=mock_cursor)
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.get_role_by_emoji(guild_id=111222333, emoji="🎮")
            
            assert result is None

    @pytest.mark.asyncio
    async def test_get_role_by_emoji_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении роли по эмодзи."""
        with patch('aiosqlite.connect', side_effect=Exception("Database error")):
            with patch('utils.role_reaction_data_manager.logger') as mock_logger:
                result = await manager.get_role_by_emoji(guild_id=111222333, emoji="🎮")
                
                assert result is None
                mock_logger.error.assert_called_once()
                assert "Ошибка при получении роли для эмодзи" in mock_logger.error.call_args[0][0]


class TestIntegrationScenarios:
    """Интеграционные тесты для различных сценариев использования."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр RoleReactionDataManager."""
        return RoleReactionDataManager(db_path=":memory:")

    @pytest.mark.asyncio
    async def test_full_workflow_scenario(self, manager):
        """Тест полного рабочего процесса: добавление, получение, удаление."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        
        # Мокаем курсор для удаления
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 1
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            # 1. Добавляем привязку
            mock_conn.execute.return_value = AsyncMock()
            add_result = await manager.add_role_reaction(
                guild_id=111222333,
                channel_id=123456,
                message_id=789012,
                emoji="🎮",
                role_id=555666777,
                description="Геймер"
            )
            assert add_result is True
            
            # 2. Удаляем привязку
            mock_conn.execute.return_value = mock_cursor
            remove_result = await manager.remove_role_reaction(guild_id=111222333, emoji="🎮")
            assert remove_result is True

    @pytest.mark.asyncio
    async def test_multiple_emoji_handling(self, manager):
        """Тест обработки множественных эмодзи."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        
        emojis = ["🎮", "🎵", "🎨", "📚"]
        role_ids = [555666777, 888999000, 111222333, 444555666]
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            # Добавляем несколько привязок
            for emoji, role_id in zip(emojis, role_ids):
                result = await manager.add_role_reaction(
                    guild_id=111222333,
                    channel_id=123456,
                    message_id=789012,
                    emoji=emoji,
                    role_id=role_id,
                    description=f"Роль для {emoji}"
                )
                assert result is True
            
            # Проверяем, что execute был вызван для каждой привязки
            assert mock_conn.execute.call_count == len(emojis)

    @pytest.mark.asyncio
    async def test_custom_emoji_handling(self, manager):
        """Тест обработки кастомных эмодзи Discord."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        
        custom_emoji = "<:custom_emoji:123456789012345678>"
        
        with patch('aiosqlite.connect', return_value=mock_conn):
            result = await manager.add_role_reaction(
                guild_id=111222333,
                channel_id=123456,
                message_id=789012,
                emoji=custom_emoji,
                role_id=555666777,
                description="Кастомная роль"
            )
            
            assert result is True
            call_args = mock_conn.execute.call_args
            assert custom_emoji in call_args[0][1]
