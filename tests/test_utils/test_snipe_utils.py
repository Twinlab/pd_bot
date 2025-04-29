import pytest
from unittest.mock import MagicMock
from utils.snipe_utils import show_sniped_message

from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_show_sniped_message():
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.channel = MagicMock()
    ctx.channel.id = 123
    await show_sniped_message(ctx)
    # Если не возникло исключений — тест прошёл
