import pytest
from unittest.mock import MagicMock
from utils.message_utils import handle_message

@pytest.mark.asyncio
async def test_handle_message():
    message = MagicMock()
    await handle_message(message)
