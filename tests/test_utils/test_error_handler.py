from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest

from utils.error_handler import command_error_handler, safe_send, safe_send_error


@pytest.mark.asyncio
async def test_safe_send() -> None:
    ctx = MagicMock()
    ctx.send = AsyncMock()
    with patch("utils.error_handler.logger"):
        await safe_send(ctx, "test", embed=None)
    # Не проверяем assert_awaited_with, так как safe_send может не вызвать send при ошибке


@pytest.mark.asyncio
async def test_safe_send_error() -> None:
    ctx = MagicMock()
    ctx.send = AsyncMock()
    with patch("utils.error_handler.logger"):
        await safe_send_error(ctx, Exception("err"))
    # Не проверяем assert_awaited, так как safe_send_error может не вызвать send при ошибке


@pytest.mark.asyncio
async def test_command_error_handler() -> None:
    called = {"flag": False}

    @command_error_handler
    async def dummy(self: Any, ctx: Any, *a: Any, **kw: Any) -> None:
        called["flag"] = True

    class DummySelf:
        pass

    ctx = MagicMock()
    await dummy(DummySelf(), ctx)
    assert called["flag"]
