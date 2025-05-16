from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.deathbattle_utils import create_deathbattle_image, get_event_and_damage, run_battle


def test_get_event_and_damage() -> None:
    event, damage = get_event_and_damage()
    assert isinstance(event, str)
    assert isinstance(damage, int)


@pytest.mark.asyncio
async def test_create_deathbattle_image() -> None:
    member1 = MagicMock()
    member2 = MagicMock()
    result = await create_deathbattle_image(member1, member2)
    assert result is None or hasattr(result, "read")  # BytesIO или None


@pytest.mark.asyncio
async def test_run_battle() -> None:
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.members = [ctx.author]
    member1 = MagicMock()
    member2 = MagicMock()
    await run_battle(ctx, member1, member2)
    # Если не возникло исключений — тест прошёл
