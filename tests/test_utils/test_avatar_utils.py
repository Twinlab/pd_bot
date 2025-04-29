import pytest
from unittest.mock import MagicMock
from utils.avatar_utils import display_avatar

@pytest.mark.asyncio
async def test_display_avatar():
    ctx = MagicMock()
    mentioned_user = MagicMock()
    await display_avatar(ctx, mentioned_user)
    await display_avatar(ctx, None)
