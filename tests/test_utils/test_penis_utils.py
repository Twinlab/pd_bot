from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.penis_utils import measure_penis


@pytest.mark.asyncio
async def test_measure_penis() -> None:
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.mention = "@author"
    target_user = MagicMock()
    target_user.mention = "@target"
    await measure_penis(ctx, target_user)
    await measure_penis(ctx, None)
