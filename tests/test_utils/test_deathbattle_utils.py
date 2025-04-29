import pytest
from utils.deathbattle_utils import (
    get_event_and_damage,
    create_deathbattle_image,
    run_battle,
)
from unittest.mock import MagicMock

def test_get_event_and_damage():
    event, damage = get_event_and_damage()
    assert isinstance(event, str)
    assert isinstance(damage, int)

@pytest.mark.asyncio
async def test_create_deathbattle_image():
    member1 = MagicMock()
    member2 = MagicMock()
    result = await create_deathbattle_image(member1, member2)
    assert result is None or hasattr(result, "read")  # BytesIO или None

from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_run_battle():
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.members = [ctx.author]
    member1 = MagicMock()
    member2 = MagicMock()
    await run_battle(ctx, member1, member2)
    # Если не возникло исключений — тест прошёл
