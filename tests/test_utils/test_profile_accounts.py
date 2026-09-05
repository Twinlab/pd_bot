"""Распознавание аккаунтов и различение ошибок внешних сервисов."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from utils.cs_api import FaceitNonRetryable, FaceitNotFound, FaceitRateLimited
from utils.profile.accounts import (
    MAX_ACCOUNT_ID,
    STEAM_ID_BASE,
    AccountInput,
    ProfileAccountService,
    cached_dota_names,
    parse_account_input,
)
from utils.profile_accounts_data_manager import AccountLinkError

STEAM_ID = str(STEAM_ID_BASE + 12345)


@pytest.mark.parametrize(
    "value",
    [
        "12345",
        STEAM_ID,
        f"https://steamcommunity.com/profiles/{STEAM_ID}/?x=1",
        f"<https://www.steamcommunity.com/profiles/{STEAM_ID}>",
        "https://www.dotabuff.com/players/12345/matches",
        "stratz.com/players/12345",
        "https://www.opendota.com/players/12345",
    ],
)
def test_steam_and_dota_inputs_resolve_to_same_account(value):
    assert parse_account_input(value, "dota") == AccountInput("steam", STEAM_ID)


@pytest.mark.parametrize(
    "value",
    [
        "example",
        "https://www.faceit.com/en/players/example",
        "faceit.com/ru/players/example/",
        "https://faceit.com/players/example",
    ],
)
def test_faceit_nickname_and_urls(value):
    assert parse_account_input(value, "cs") == AccountInput("faceit", "example")


def test_numeric_faceit_nickname_is_not_mistaken_for_dota_id():
    assert parse_account_input("12345", "cs") == AccountInput("faceit", "12345")
    assert parse_account_input(STEAM_ID, "cs") == AccountInput("steam", STEAM_ID)


def test_vanity_is_identified_without_network():
    assert parse_account_input("steamcommunity.com/id/example", "dota") == AccountInput(
        "vanity", "example"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0",
        "-1",
        str(STEAM_ID_BASE),
        str(STEAM_ID_BASE + MAX_ACCOUNT_ID + 1),
        "https://steamcommunity.com.evil.test/id/example",
        "https://steamcommunity.com@evil.test/id/example",
        "https://evil.test@steamcommunity.com/id/example",
        "https://steamcommunity.com:9000/id/example",
        "file:///profiles/12345",
        "https://steamcommunity.com/profiles/12345",
        "https://steamcommunity.com/id/a%2Fb",
        "https://faceit.com/en/players/a%3Fb",
        "https://[invalid",
        "https://steamcommunity.com/groups/example",
        "١٢٣٤٥",
        "a" * 301,
    ],
)
def test_unsupported_and_unsafe_input_is_rejected(value):
    with pytest.raises(AccountLinkError):
        parse_account_input(value, "dota")


@pytest.fixture
def service():
    settings = SimpleNamespace(
        steam_api_key=None, faceit_api_key="test", limits=SimpleNamespace(links_max_per_user=5)
    )
    instance = ProfileAccountService(settings)
    instance.manager = MagicMock(add_link=AsyncMock(), remove_link=AsyncMock())
    return instance


@pytest.fixture
def faceit_player():
    return {
        "player_id": "faceit-123",
        "nickname": "example",
        "steam_id_64": STEAM_ID,
        "steam_nickname": "Steam Name",
        "games": {"cs2": {"game_player_id": STEAM_ID}},
        "avatar": "https://example.com/avatar.png",
    }


async def test_numeric_dota_needs_no_api_key_and_does_not_save(service):
    with patch("utils.profile.accounts.faceit_get", new_callable=AsyncMock) as api:
        account = await service.resolve(STEAM_ID, "dota")
    assert account.identifier == "12345"
    assert account.url.endswith(STEAM_ID)
    api.assert_not_awaited()
    service.manager.add_link.assert_not_awaited()


async def test_vanity_without_key_has_actionable_error(service):
    with pytest.raises(AccountLinkError, match="ID Dota"):
        await service.resolve("https://steamcommunity.com/id/example", "dota")


async def test_vanity_preview_resolves_and_caches_name(service):
    service.settings.steam_api_key = "test"
    service._steam_request = AsyncMock(
        side_effect=[
            {"success": 1, "steamid": STEAM_ID},
            {
                "players": [
                    {
                        "steamid": STEAM_ID,
                        "personaname": "Steam Name",
                        "avatarfull": "https://example.com/a.png",
                    }
                ]
            },
        ]
    )
    with patch("utils.profile.accounts.save_to_cache", new_callable=AsyncMock) as cache:
        account = await service.resolve("https://steamcommunity.com/id/example", "dota")
    assert account.identifier == "12345"
    assert account.name == "Steam Name"
    assert account.avatar == "https://example.com/a.png"
    cache.assert_awaited_once()
    service.manager.add_link.assert_not_awaited()


async def test_steam_to_faceit_lookup(service, faceit_player):
    with patch(
        "utils.profile.accounts.faceit_get", new_callable=AsyncMock, return_value=faceit_player
    ) as api:
        account = await service.resolve(f"https://steamcommunity.com/profiles/{STEAM_ID}", "cs")
    assert account.identifier == "faceit-123"
    assert api.await_args.kwargs["params"] == {"game": "cs2", "game_player_id": STEAM_ID}


async def test_faceit_link_can_supply_dota_id(service, faceit_player):
    with (
        patch(
            "utils.profile.accounts.faceit_get", new_callable=AsyncMock, return_value=faceit_player
        ),
        patch("utils.profile.accounts.save_to_cache", new_callable=AsyncMock),
    ):
        account = await service.resolve("faceit.com/en/players/example", "dota")
    assert account.identifier == "12345"
    assert account.name == "Steam Name"


@pytest.mark.parametrize(
    ("result", "error", "message"),
    [
        (None, None, "не ответил"),
        (None, FaceitNotFound(), "не найден"),
        (None, FaceitRateLimited(1), "подождать"),
        (None, FaceitNonRetryable(), "недоступен"),
        ({"player_id": "id", "nickname": "name", "games": {}}, None, "не подключён"),
        ({"nickname": "name"}, None, "неполный"),
    ],
)
async def test_faceit_errors_are_distinguished(service, result, error, message):
    with patch(
        "utils.profile.accounts.faceit_get",
        new_callable=AsyncMock,
        return_value=result,
        side_effect=error,
    ):
        with pytest.raises(AccountLinkError, match=message):
            await service.resolve("example", "cs")


async def test_steam_transport_error_does_not_expose_key(service):
    service.settings.steam_api_key = "do-not-expose-this"
    service._session = MagicMock(closed=False)
    service._session.get.side_effect = aiohttp.ClientError("URL contains do-not-expose-this")
    with pytest.raises(AccountLinkError) as error:
        await service.resolve("steamcommunity.com/id/example", "dota")
    assert "do-not-expose-this" not in str(error.value)
    assert error.value.__suppress_context__


async def test_steam_request_uses_fixed_api_and_disables_redirects(service):
    service.settings.steam_api_key = "test"
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={"response": {"success": 1, "steamid": STEAM_ID}})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    service._session = MagicMock(closed=False)
    service._session.get.return_value = response
    result = await service._steam_request("ResolveVanityURL/v1", {"vanityurl": "example"})
    assert result["steamid"] == STEAM_ID
    service._session.get.assert_called_once_with(
        "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/",
        params={"vanityurl": "example", "key": "test"},
        allow_redirects=False,
    )


async def test_overall_timeout_is_actionable(service):
    service._resolve = AsyncMock(side_effect=TimeoutError)
    with pytest.raises(AccountLinkError, match="слишком много времени"):
        await service.resolve("12345", "dota")


async def test_save_and_remove_use_owner_and_current_limit(service):
    account = await service.resolve("12345", "dota")
    await service.save(42, account)
    service.manager.add_link.assert_awaited_once_with(42, "dota", "12345", "ID 12345", limit=5)
    await service.remove(42, account)
    service.manager.remove_link.assert_awaited_once_with(42, "dota", "12345")


async def test_close_releases_session(service):
    session = MagicMock(close=AsyncMock())
    service._session = session
    await service.close()
    session.close.assert_awaited_once()
    assert service._session is None


async def test_cached_names_use_only_local_cache():
    with patch(
        "utils.profile.accounts.get_cached_response",
        new_callable=AsyncMock,
        side_effect=[{"name": "Name"}, None],
    ):
        assert await cached_dota_names([1, 2]) == {1: "Name"}
