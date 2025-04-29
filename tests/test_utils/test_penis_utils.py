import pytest
from unittest.mock import MagicMock
from utils.penis_utils import measure_penis

@pytest.mark.asyncio
async def test_measure_penis():
    ctx = MagicMock()
    target_user = MagicMock()
    await measure_penis(ctx, target_user)
    await measure_penis(ctx, None)
