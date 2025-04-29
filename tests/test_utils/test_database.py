import pytest
from utils.database import initialize_database

@pytest.mark.asyncio
async def test_initialize_database(monkeypatch):
    class DummyConn:
        async def execute(self, *a, **kw): return None
        async def commit(self): return None
        async def close(self): return None
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return None
    async def dummy_connect(*a, **kw): return DummyConn()
    monkeypatch.setattr("aiosqlite.connect", dummy_connect)

    await initialize_database()
    # Проверка повторного вызова (идемпотентность)
    await initialize_database()
