"""Проверки привязок на настоящей изолированной SQLite-базе."""

import asyncio

import pytest
from tortoise import Tortoise

from utils.models import CsLink, Link
from utils.profile_accounts_data_manager import AccountLinkError, ProfileAccountsDataManager


@pytest.fixture
async def manager():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["utils.models"]})
    await Tortoise.generate_schemas()
    yield ProfileAccountsDataManager()
    await Tortoise.close_connections()


@pytest.mark.parametrize("game", ["dota", "cs"])
async def test_duplicate_is_rejected_but_another_user_can_link(manager, game):
    await manager.add_link(1, game, "123", "nickname", limit=5)
    with pytest.raises(AccountLinkError, match="уже привязан"):
        await manager.add_link(1, game, "123", "nickname", limit=5)
    await manager.add_link(2, game, "123", "nickname", limit=5)


@pytest.mark.parametrize("game", ["dota", "cs"])
async def test_simultaneous_additions_cannot_exceed_limit(manager, game):
    results = await asyncio.gather(
        manager.add_link(1, game, "123", "one", limit=1),
        manager.add_link(1, game, "456", "two", limit=1),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, AccountLinkError) for result in results) == 1
    model = Link if game == "dota" else CsLink
    assert await model.filter(discord_user_id=1).count() == 1


@pytest.mark.parametrize("game", ["dota", "cs"])
async def test_unlink_is_scoped_to_owner_and_selected_account(manager, game):
    for owner, identifier in [(1, "123"), (1, "456"), (2, "123")]:
        await manager.add_link(owner, game, identifier, "name", limit=5)
    await manager.remove_link(1, game, "123")
    model = Link if game == "dota" else CsLink
    assert await model.filter(discord_user_id=1).count() == 1
    assert await model.filter(discord_user_id=2).count() == 1
    with pytest.raises(AccountLinkError, match="уже отвязан"):
        await manager.remove_link(1, game, "123")
