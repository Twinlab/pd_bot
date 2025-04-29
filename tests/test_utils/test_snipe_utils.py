import pytest
from unittest.mock import MagicMock
from utils.snipe_utils import show_sniped_message

@pytest.mark.asyncio
async def test_show_sniped_message():
    ctx = MagicMock()
    await show_sniped_message(ctx)
    # Если не возникло исключений — тест прошёл
