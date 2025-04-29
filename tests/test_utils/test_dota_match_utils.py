import pytest
from utils.dota_match_utils import get_match_data, handle_lastmatch
from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_get_match_data():
    user_links = {"user1": [123]}
    user_id = "user1"
    stratz_api_key = "fake_key"
    result = await get_match_data(user_links, user_id, stratz_api_key)
    assert isinstance(result, tuple)
    assert len(result) == 4

@pytest.mark.asyncio
async def test_handle_lastmatch():
    ctx = MagicMock()
    user_links_list = [123]
    member = MagicMock()
    await handle_lastmatch(ctx, user_links_list, member)
    await handle_lastmatch(ctx, user_links_list, None)
