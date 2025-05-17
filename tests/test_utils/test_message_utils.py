from unittest.mock import MagicMock

import pytest

from utils.message_utils import handle_message


@pytest.mark.asyncio
async def test_handle_message() -> None:
    message = MagicMock()
    await handle_message(message)
