import pytest

from utils.links_data_manager import LinksDataManager


@pytest.fixture
def manager(monkeypatch):
    class DummyConn:
        async def execute(self, *a, **kw):
            return DummyCursor()

        async def commit(self):
            return None

        async def close(self):
            return None

    class DummyCursor:
        async def fetchone(self):
            return None

        async def fetchall(self):
            return []

    async def dummy_connect(*a, **kw):
        return DummyConn()

    monkeypatch.setattr("aiosqlite.connect", dummy_connect)
    return LinksDataManager(db_path=":memory:")


@pytest.mark.asyncio
async def test_add_link(manager):
    result = await manager.add_link(1, 123)
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_remove_link(manager):
    result = await manager.remove_link(1, 123)
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_remove_all_links(manager):
    result = await manager.remove_all_links(1)
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_get_links(manager):
    result = await manager.get_links(1)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_all_links_data(manager):
    result = await manager.get_all_links_data()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_migrate_links_from_json(manager):
    await manager.migrate_links_from_json(json_file_path="fake.json")
