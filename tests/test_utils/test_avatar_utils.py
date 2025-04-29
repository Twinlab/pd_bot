import pytest
from unittest.mock import MagicMock
from utils.avatar_utils import display_avatar

from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_display_avatar():
    ctx = MagicMock()
    ctx.send = AsyncMock()
    mentioned_user = MagicMock()
    mentioned_user.display_avatar.with_size.return_value.url = "http://example.com/avatar.png"
    mentioned_user.avatar = MagicMock()
    mentioned_user.avatar.with_size.return_value.url = "http://example.com/global_avatar.png"
    mentioned_user.default_avatar.with_size.return_value.url = "http://example.com/default_avatar.png"
    mentioned_user.display_name = "TestUser"
    await display_avatar(ctx, mentioned_user)
    await display_avatar(ctx, None)
