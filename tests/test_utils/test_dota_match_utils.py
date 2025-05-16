from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.dota_match_utils import get_match_data, handle_lastmatch


@pytest.mark.asyncio
async def test_get_match_data() -> None:
    user_links = {"user1": [123]}
    user_id = "user1"
    stratz_api_key = "fake_key"
    result = await get_match_data(user_links, user_id, stratz_api_key)
    assert isinstance(result, tuple)
    assert len(result) == 4


@pytest.mark.asyncio
async def test_handle_lastmatch() -> None:
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.config = {"STRATZ_API_KEY": "fake"}
    ctx.guild = MagicMock()
    user_links_list = [123]
    member = MagicMock()
    member.id = 123
    member.mention = "@user"
    await handle_lastmatch(ctx, user_links_list, member)
    await handle_lastmatch(ctx, user_links_list, None)
