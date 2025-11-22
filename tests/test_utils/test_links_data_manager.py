"""Тесты для LinksDataManager - управление привязками Steam ID к Discord ID."""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.links_data_manager import LinksDataManager
from utils.models import Link


@pytest.fixture
def manager():
    """Создает экземпляр LinksDataManager."""
    return LinksDataManager()


class TestLinksDataManagerInit:
    """Тесты инициализации LinksDataManager."""

    def test_init(self):
        """Тест инициализации."""
        manager = LinksDataManager()
        assert manager is not None


class TestAddLink:
    """Тесты метода add_link."""

    @pytest.mark.asyncio
    async def test_add_link_success(self, manager):
        """Тест успешного добавления привязки."""
        with patch("utils.links_data_manager.Link.get_or_create", new_callable=AsyncMock) as mock_get_or_create:
            mock_get_or_create.return_value = (MagicMock(), True)
            
            result = await manager.add_link(123456789, 987654321)
            
            assert result is True
            mock_get_or_create.assert_called_once_with(discord_user_id=123456789, steam_id=987654321)

    @pytest.mark.asyncio
    async def test_add_link_already_exists(self, manager):
        """Тест добавления уже существующей привязки."""
        with patch("utils.links_data_manager.Link.get_or_create", new_callable=AsyncMock) as mock_get_or_create:
            mock_get_or_create.return_value = (MagicMock(), False)
            
            result = await manager.add_link(123456789, 987654321)
            
            assert result is False
            mock_get_or_create.assert_called_once_with(discord_user_id=123456789, steam_id=987654321)

    @pytest.mark.asyncio
    async def test_add_link_database_error(self, manager):
        """Тест обработки ошибки базы данных при добавлении."""
        with patch("utils.links_data_manager.Link.get_or_create", new_callable=AsyncMock) as mock_get_or_create:
            mock_get_or_create.side_effect = Exception("Database error")
            
            result = await manager.add_link(123456789, 987654321)
            
            assert result is False


class TestRemoveLink:
    """Тесты метода remove_link."""

    @pytest.mark.asyncio
    async def test_remove_link_success(self, manager):
        """Тест успешного удаления привязки."""
        with patch("utils.links_data_manager.Link.filter") as mock_filter:
            mock_delete = AsyncMock(return_value=1)
            mock_filter.return_value.delete = mock_delete
            
            result = await manager.remove_link(123456789, 987654321)
            
            assert result is True
            mock_filter.assert_called_once_with(discord_user_id=123456789, steam_id=987654321)
            mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_link_not_found(self, manager):
        """Тест удаления несуществующей привязки."""
        with patch("utils.links_data_manager.Link.filter") as mock_filter:
            mock_delete = AsyncMock(return_value=0)
            mock_filter.return_value.delete = mock_delete
            
            result = await manager.remove_link(123456789, 987654321)
            
            assert result is False
            mock_filter.assert_called_once_with(discord_user_id=123456789, steam_id=987654321)

    @pytest.mark.asyncio
    async def test_remove_link_database_error(self, manager):
        """Тест обработки ошибки базы данных при удалении."""
        with patch("utils.links_data_manager.Link.filter") as mock_filter:
            mock_filter.side_effect = Exception("Database error")
            
            result = await manager.remove_link(123456789, 987654321)
            
            assert result is False


class TestRemoveAllLinks:
    """Тесты метода remove_all_links."""

    @pytest.mark.asyncio
    async def test_remove_all_links_success(self, manager):
        """Тест успешного удаления всех привязок."""
        with patch("utils.links_data_manager.Link.filter") as mock_filter:
            mock_delete = AsyncMock(return_value=3)
            mock_filter.return_value.delete = mock_delete
            
            result = await manager.remove_all_links(123456789)
            
            assert result == 3
            mock_filter.assert_called_once_with(discord_user_id=123456789)

    @pytest.mark.asyncio
    async def test_remove_all_links_database_error(self, manager):
        """Тест обработки ошибки базы данных при удалении всех привязок."""
        with patch("utils.links_data_manager.Link.filter") as mock_filter:
            mock_filter.side_effect = Exception("Database error")
            
            result = await manager.remove_all_links(123456789)
            
            assert result == 0


class TestGetLinks:
    """Тесты метода get_links."""

    @pytest.mark.asyncio
    async def test_get_links_success(self, manager):
        """Тест успешного получения привязок."""
        with patch("utils.links_data_manager.Link.filter") as mock_filter:
            mock_values_list = AsyncMock(return_value=[987654321, 111111111])
            mock_filter.return_value.values_list = mock_values_list
            
            result = await manager.get_links(123456789)
            
            assert result == [987654321, 111111111]
            mock_filter.assert_called_once_with(discord_user_id=123456789)
            mock_values_list.assert_called_once_with("steam_id", flat=True)

    @pytest.mark.asyncio
    async def test_get_links_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении привязок."""
        with patch("utils.links_data_manager.Link.filter") as mock_filter:
            mock_filter.side_effect = Exception("Database error")
            
            result = await manager.get_links(123456789)
            
            assert result == []


class TestGetAllLinksData:
    """Тесты метода get_all_links_data."""

    @pytest.mark.asyncio
    async def test_get_all_links_data_success(self, manager):
        """Тест успешного получения всех данных о привязках."""
        with patch("utils.links_data_manager.Link.all", new_callable=AsyncMock) as mock_all:
            mock_link1 = MagicMock(discord_user_id=123, steam_id=111)
            mock_link2 = MagicMock(discord_user_id=123, steam_id=222)
            mock_link3 = MagicMock(discord_user_id=456, steam_id=333)
            mock_all.return_value = [mock_link1, mock_link2, mock_link3]
            
            result = await manager.get_all_links_data()
            
            assert result == {123: [111, 222], 456: [333]}

    @pytest.mark.asyncio
    async def test_get_all_links_data_database_error(self, manager):
        """Тест обработки ошибки базы данных при получении всех данных."""
        with patch("utils.links_data_manager.Link.all", new_callable=AsyncMock) as mock_all:
            mock_all.side_effect = Exception("Database error")
            
            result = await manager.get_all_links_data()
            
            assert result == {}


class TestMigrateLinksFromJson:
    """Тесты метода migrate_links_from_json."""

    @pytest.mark.asyncio
    async def test_migrate_from_json_new_format(self, manager):
        """Тест миграции из JSON нового формата."""
        test_data = {
            "123456789": [987654321, 111111111],
            "999888777": [222222222]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            with patch("utils.links_data_manager.Link.bulk_create", new_callable=AsyncMock) as mock_bulk_create:
                result = await manager.migrate_links_from_json(json_path)
                
                assert result == 3
                mock_bulk_create.assert_called_once()
                args, kwargs = mock_bulk_create.call_args
                assert len(args[0]) == 3
                assert kwargs["ignore_conflicts"] is True
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_old_format(self, manager):
        """Тест миграции из JSON старого формата."""
        test_data = [
            {"user": 123456789, "links": [987654321, 111111111]},
            {"user": 999888777, "links": [222222222]}
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            with patch("utils.links_data_manager.Link.bulk_create", new_callable=AsyncMock) as mock_bulk_create:
                result = await manager.migrate_links_from_json(json_path)
                
                assert result == 3
                mock_bulk_create.assert_called_once()
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_file_not_found(self, manager):
        """Тест миграции когда файл не найден."""
        result = await manager.migrate_links_from_json("nonexistent.json")
        assert result == 0

    @pytest.mark.asyncio
    async def test_migrate_from_json_database_error(self, manager):
        """Тест обработки ошибки базы данных при миграции."""
        test_data = {"123456789": [987654321]}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            with patch("utils.links_data_manager.Link.bulk_create", new_callable=AsyncMock) as mock_bulk_create:
                mock_bulk_create.side_effect = Exception("Database error")
                
                result = await manager.migrate_links_from_json(json_path)
                
                assert result == 0
        finally:
            os.unlink(json_path)