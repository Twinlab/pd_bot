"""Тесты для LinksDataManager - управление привязками Steam ID к Discord ID."""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.links_data_manager import LinksDataManager


@pytest.fixture
def temp_db():
    """Создает временную базу данных для тестов."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def manager(temp_db):
    """Создает экземпляр LinksDataManager с временной БД."""
    return LinksDataManager(db_path=temp_db)


@pytest.fixture
def mock_manager(monkeypatch):
    """Создает мок LinksDataManager для тестов без реальной БД."""
    class MockCursor:
        def __init__(self, rowcount=0, total_changes=0, fetchone_result=None, fetchall_result=None):
            self.rowcount = rowcount
            self.total_changes = total_changes
            self._fetchone_result = fetchone_result
            self._fetchall_result = fetchall_result or []
            self._fetch_index = 0

        async def fetchone(self):
            return self._fetchone_result

        async def fetchall(self):
            return self._fetchall_result

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._fetch_index < len(self._fetchall_result):
                result = self._fetchall_result[self._fetch_index]
                self._fetch_index += 1
                return result
            raise StopAsyncIteration

    class MockConnection:
        def __init__(self):
            self.total_changes = 0
            self._cursor = None

        async def execute(self, query, params=None):
            self._cursor = MockCursor()
            return self._cursor

        async def executemany(self, query, params_list):
            self._cursor = MockCursor(rowcount=len(params_list))
            return self._cursor

        async def commit(self):
            pass

        async def rollback(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def mock_connect(*args, **kwargs):
        return MockConnection()

    monkeypatch.setattr("aiosqlite.connect", mock_connect)
    return LinksDataManager(db_path=":memory:")


class TestLinksDataManagerInit:
    """Тесты инициализации LinksDataManager."""

    def test_init_default_path(self):
        """Тест инициализации с путем по умолчанию."""
        manager = LinksDataManager()
        assert manager.db_path is not None
        assert isinstance(manager.db_path, str)

    def test_init_custom_path(self):
        """Тест инициализации с пользовательским путем."""
        custom_path = "/custom/path/test.db"
        manager = LinksDataManager(db_path=custom_path)
        assert manager.db_path == custom_path


class TestAddLink:
    """Тесты метода add_link."""

    @pytest.mark.asyncio
    async def test_add_link_success(self, mock_manager, monkeypatch):
        """Тест успешного добавления привязки."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        
        mock_db = MagicMock()
        mock_db.total_changes = 1
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        class MockConnect:
            def __init__(self, *args, **kwargs):
                pass
            
            async def __aenter__(self):
                return mock_db
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.add_link(123456789, 987654321)
        assert result is True

    @pytest.mark.asyncio
    async def test_add_link_already_exists(self, mock_manager, monkeypatch):
        """Тест добавления уже существующей привязки."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        
        mock_db = MagicMock()
        mock_db.total_changes = 0
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        class MockConnect:
            def __init__(self, *args, **kwargs):
                pass
            
            async def __aenter__(self):
                return mock_db
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.add_link(123456789, 987654321)
        assert result is False

    @pytest.mark.asyncio
    async def test_add_link_database_error(self, mock_manager, monkeypatch):
        """Тест обработки ошибки базы данных при добавлении."""
        class MockConnect:
            def __init__(self, *args, **kwargs):
                raise Exception("Database connection error")

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.add_link(123456789, 987654321)
        assert result is False


class TestRemoveLink:
    """Тесты метода remove_link."""

    @pytest.mark.asyncio
    async def test_remove_link_success(self, mock_manager, monkeypatch):
        """Тест успешного удаления привязки."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        class MockConnect:
            def __init__(self, *args, **kwargs):
                pass
            
            async def __aenter__(self):
                return mock_db
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.remove_link(123456789, 987654321)
        assert result is True

    @pytest.mark.asyncio
    async def test_remove_link_not_found(self, mock_manager, monkeypatch):
        """Тест удаления несуществующей привязки."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        class MockConnect:
            def __init__(self, *args, **kwargs):
                pass
            
            async def __aenter__(self):
                return mock_db
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.remove_link(123456789, 987654321)
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_link_database_error(self, mock_manager, monkeypatch):
        """Тест обработки ошибки базы данных при удалении."""
        class MockConnect:
            def __init__(self, *args, **kwargs):
                raise Exception("Database connection error")

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.remove_link(123456789, 987654321)
        assert result is False


class TestRemoveAllLinks:
    """Тесты метода remove_all_links."""

    @pytest.mark.asyncio
    async def test_remove_all_links_success(self, mock_manager, monkeypatch):
        """Тест успешного удаления всех привязок."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 3
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        class MockConnect:
            def __init__(self, *args, **kwargs):
                pass
            
            async def __aenter__(self):
                return mock_db
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.remove_all_links(123456789)
        assert result == 3

    @pytest.mark.asyncio
    async def test_remove_all_links_no_links(self, mock_manager, monkeypatch):
        """Тест удаления всех привязок когда их нет."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        class MockConnect:
            def __init__(self, *args, **kwargs):
                pass
            
            async def __aenter__(self):
                return mock_db
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.remove_all_links(123456789)
        assert result == 0

    @pytest.mark.asyncio
    async def test_remove_all_links_database_error(self, mock_manager, monkeypatch):
        """Тест обработки ошибки базы данных при удалении всех привязок."""
        class MockConnect:
            def __init__(self, *args, **kwargs):
                raise Exception("Database connection error")

        monkeypatch.setattr("aiosqlite.connect", MockConnect)
        
        result = await mock_manager.remove_all_links(123456789)
        assert result == 0


class TestGetLinks:
    """Тесты метода get_links."""

    @pytest.mark.asyncio
    async def test_get_links_success(self, mock_manager, monkeypatch):
        """Тест успешного получения привязок."""
        mock_cursor = MagicMock()
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_cursor)
        
        # Имитируем async for
        async def mock_anext():
            for row in [(987654321,), (111111111,)]:
                yield row
        
        mock_cursor.__anext__ = mock_anext().__anext__
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        async def mock_connect(*args, **kwargs):
            return mock_db

        monkeypatch.setattr("aiosqlite.connect", mock_connect)
        
        result = await mock_manager.get_links(123456789)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_links_empty(self, mock_manager, monkeypatch):
        """Тест получения пустого списка привязок."""
        mock_cursor = MagicMock()
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_cursor)
        
        async def mock_anext():
            return
            yield  # unreachable
        
        mock_cursor.__anext__ = mock_anext().__anext__
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        async def mock_connect(*args, **kwargs):
            return mock_db

        monkeypatch.setattr("aiosqlite.connect", mock_connect)
        
        result = await mock_manager.get_links(123456789)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_links_database_error(self, mock_manager, monkeypatch):
        """Тест обработки ошибки базы данных при получении привязок."""
        async def mock_connect(*args, **kwargs):
            raise Exception("Database connection error")

        monkeypatch.setattr("aiosqlite.connect", mock_connect)
        
        result = await mock_manager.get_links(123456789)
        assert result == []


class TestGetAllLinksData:
    """Тесты метода get_all_links_data."""

    @pytest.mark.asyncio
    async def test_get_all_links_data_success(self, mock_manager, monkeypatch):
        """Тест успешного получения всех данных о привязках."""
        mock_cursor = MagicMock()
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_cursor)
        
        async def mock_anext():
            for row in [(123456789, 987654321), (123456789, 111111111), (999888777, 222222222)]:
                yield row
        
        mock_cursor.__anext__ = mock_anext().__anext__
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        async def mock_connect(*args, **kwargs):
            return mock_db

        monkeypatch.setattr("aiosqlite.connect", mock_connect)
        
        result = await mock_manager.get_all_links_data()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_all_links_data_empty(self, mock_manager, monkeypatch):
        """Тест получения пустых данных о привязках."""
        mock_cursor = MagicMock()
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_cursor)
        
        async def mock_anext():
            return
            yield  # unreachable
        
        mock_cursor.__anext__ = mock_anext().__anext__
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        async def mock_connect(*args, **kwargs):
            return mock_db

        monkeypatch.setattr("aiosqlite.connect", mock_connect)
        
        result = await mock_manager.get_all_links_data()
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_all_links_data_database_error(self, mock_manager, monkeypatch):
        """Тест обработки ошибки базы данных при получении всех данных."""
        async def mock_connect(*args, **kwargs):
            raise Exception("Database connection error")

        monkeypatch.setattr("aiosqlite.connect", mock_connect)
        
        result = await mock_manager.get_all_links_data()
        assert result == {}


class TestMigrateLinksFromJson:
    """Тесты метода migrate_links_from_json."""

    @pytest.mark.asyncio
    async def test_migrate_from_json_new_format(self, mock_manager, monkeypatch):
        """Тест миграции из JSON нового формата."""
        # Создаем временный JSON файл
        test_data = {
            "123456789": [987654321, 111111111],
            "999888777": [222222222]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            mock_cursor = MagicMock()
            mock_cursor.rowcount = 3
            
            mock_db = MagicMock()
            mock_db.execute = AsyncMock()
            mock_db.executemany = AsyncMock(return_value=mock_cursor)
            mock_db.commit = AsyncMock()
            mock_db.rollback = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=None)

            class MockConnect:
                def __init__(self, *args, **kwargs):
                    pass
                
                async def __aenter__(self):
                    return mock_db
                
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    return None

            monkeypatch.setattr("aiosqlite.connect", MockConnect)
            
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 3
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_old_format(self, mock_manager, monkeypatch):
        """Тест миграции из JSON старого формата."""
        test_data = [
            {"user": 123456789, "links": [987654321, 111111111]},
            {"user": 999888777, "links": [222222222]}
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            mock_cursor = MagicMock()
            mock_cursor.rowcount = 3
            
            mock_db = MagicMock()
            mock_db.execute = AsyncMock()
            mock_db.executemany = AsyncMock(return_value=mock_cursor)
            mock_db.commit = AsyncMock()
            mock_db.rollback = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=None)

            class MockConnect:
                def __init__(self, *args, **kwargs):
                    pass
                
                async def __aenter__(self):
                    return mock_db
                
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    return None

            monkeypatch.setattr("aiosqlite.connect", MockConnect)
            
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 3
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_file_not_found(self, mock_manager):
        """Тест миграции когда файл не найден."""
        result = await mock_manager.migrate_links_from_json("nonexistent.json")
        assert result == 0

    @pytest.mark.asyncio
    async def test_migrate_from_json_empty_file(self, mock_manager):
        """Тест миграции из пустого файла."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json_path = f.name

        try:
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 0
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_invalid_format(self, mock_manager):
        """Тест миграции из JSON с неверным форматом."""
        test_data = "invalid json format"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(test_data)
            json_path = f.name

        try:
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 0
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_invalid_user_id(self, mock_manager, monkeypatch):
        """Тест миграции с некорректными user_id."""
        test_data = {
            "invalid_user_id": [987654321],
            "123456789": [111111111]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            mock_cursor = MagicMock()
            mock_cursor.rowcount = 1
            
            mock_db = MagicMock()
            mock_db.execute = AsyncMock()
            mock_db.executemany = AsyncMock(return_value=mock_cursor)
            mock_db.commit = AsyncMock()
            mock_db.rollback = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=None)

            class MockConnect:
                def __init__(self, *args, **kwargs):
                    pass
                
                async def __aenter__(self):
                    return mock_db
                
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    return None

            monkeypatch.setattr("aiosqlite.connect", MockConnect)
            
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 1  # Только валидная запись
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_invalid_steam_id(self, mock_manager, monkeypatch):
        """Тест миграции с некорректными steam_id."""
        test_data = {
            "123456789": [987654321, "invalid_steam_id", 111111111]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            mock_cursor = MagicMock()
            mock_cursor.rowcount = 2
            
            mock_db = MagicMock()
            mock_db.execute = AsyncMock()
            mock_db.executemany = AsyncMock(return_value=mock_cursor)
            mock_db.commit = AsyncMock()
            mock_db.rollback = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=None)

            class MockConnect:
                def __init__(self, *args, **kwargs):
                    pass
                
                async def __aenter__(self):
                    return mock_db
                
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    return None

            monkeypatch.setattr("aiosqlite.connect", MockConnect)
            
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 2  # Только валидные записи
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_database_error(self, mock_manager, monkeypatch):
        """Тест обработки ошибки базы данных при миграции."""
        test_data = {"123456789": [987654321]}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            mock_db = MagicMock()
            mock_db.execute = AsyncMock()
            mock_db.executemany = AsyncMock(side_effect=Exception("Database error"))
            mock_db.rollback = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=None)

            class MockConnect:
                def __init__(self, *args, **kwargs):
                    pass
                
                async def __aenter__(self):
                    return mock_db
                
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    return None

            monkeypatch.setattr("aiosqlite.connect", MockConnect)
            
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 0
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_no_links_to_insert(self, mock_manager):
        """Тест миграции когда нет данных для вставки."""
        test_data = {}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 0
        finally:
            os.unlink(json_path)

    @pytest.mark.asyncio
    async def test_migrate_from_json_unknown_format(self, mock_manager):
        """Тест миграции с неизвестным форматом данных."""
        test_data = 12345  # Ни dict, ни list
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            json_path = f.name

        try:
            result = await mock_manager.migrate_links_from_json(json_path)
            assert result == 0
        finally:
            os.unlink(json_path)
