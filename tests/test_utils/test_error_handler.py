import pytest
from unittest.mock import AsyncMock, MagicMock
from utils.error_handler import command_error_handler, safe_send_error, safe_send

@pytest.mark.asyncio
async def test_safe_send():
    ctx = MagicMock()
    ctx.send = AsyncMock()
    await safe_send(ctx, "test", embed=None)
    ctx.send.assert_awaited_with("test", embed=None)

@pytest.mark.asyncio
async def test_safe_send_error():
    ctx = MagicMock()
    ctx.send = AsyncMock()
    await safe_send_error(ctx, Exception("err"))
    ctx.send.assert_awaited()

@pytest.mark.asyncio
async def test_command_error_handler():
    called = {"flag": False}
    @command_error_handler
    async def dummy(self, ctx, *a, **kw):
        called["flag"] = True
    class DummySelf: pass
    ctx = MagicMock()
    await dummy(DummySelf(), ctx)
    assert called["flag"]
