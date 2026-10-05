"""HTTP-контракт кабинета проверяется на loopback без Discord и настоящей БД."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from aiohttp.test_utils import TestClient, TestServer
from pydantic import SecretStr

from config.settings import BotSettings, PortalApiConfig, QuotesConfig
from tests.test_utils.test_quote_service import make_channel
from utils.portal.api import PortalApi, load_portal_token
from utils.profile.builder import FaceitAccount, ProfileAccounts, ProfilePeriod, ProfileStats
from utils.quotes.service import QuotePermissionError, QuoteService
from utils.quotes.store import QuoteRecord

TOKEN = "test-portal-token-" + "x" * 32
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def headers(actor: int = 100) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", "X-PDRoom-User-ID": str(actor)}


def member(user_id: int, guild: MagicMock) -> MagicMock:
    result = MagicMock(spec=discord.Member)
    result.id = user_id
    result.guild = guild
    result.bot = False
    result.name = "member"
    result.display_name = "Участник"
    result.display_avatar.with_size.return_value.url = "https://cdn.discordapp.com/embed/avatars/0.png"
    result.joined_at = NOW - timedelta(days=100)
    return result


@asynccontextmanager
async def portal_harness(tmp_path):
    """Поднимает настоящий HTTP-адаптер с fake Discord для межсервисных проверок."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = 999
    guild.unavailable = False
    guild.channels = [make_channel(10), make_channel(11, public=False), make_channel(12, nsfw=True)]
    guild.threads = []
    guild.get_channel_or_thread.side_effect = lambda cid: next(
        (channel for channel in guild.channels if channel.id == cid), None
    )
    guild.fetch_member = AsyncMock(side_effect=lambda uid: member(uid, guild))
    service = QuoteService(QuotesConfig(generated_path=str(tmp_path / "quotes"), min_free_bytes=0), 1)
    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False
    bot.get_guild.return_value = guild
    bot.get_cog.return_value = SimpleNamespace(quotes=service)
    builder = MagicMock()
    builder.build_stats = AsyncMock(return_value=ProfileStats(
        period=ProfilePeriod("month", 2026, 10), messages=8, voice_seconds=90,
        reactions=12, top_games=[("Dota 2", 120)], message_rank=9, voice_rank=7,
        reaction_rank=4, data_since="2026-01-01",
    ))
    builder.build_accounts = AsyncMock(return_value=ProfileAccounts(
        dota_ids=(123,), dota_names={123: "Dota name"},
        faceit=(FaceitAccount("a-faceit-uuid", "faceit name"),),
    ))
    config = PortalApiConfig()
    api = PortalApi(bot, config, TOKEN, 1, builder=builder)
    async with TestClient(TestServer(api.create_app())) as client:
        yield SimpleNamespace(
            api=api, client=client, config=config, bot=bot, guild=guild,
            service=service, builder=builder,
        )


@pytest.fixture
async def portal(tmp_path):
    async with portal_harness(tmp_path) as harness:
        yield harness


async def save_quote(portal, message_id=1000, *, saved_by=100, author_id=300, channel_id=10, guild_id=1):
    data = b"RIFF" + (12).to_bytes(4, "little") + b"WEBP" + b"testdata"
    record = QuoteRecord(
        message_id=message_id, guild_id=guild_id, channel_id=channel_id,
        author_id=author_id, author_name="author", author_display_name="Автор",
        created_at=NOW, saved_by=saved_by, saved_at=NOW + timedelta(seconds=message_id),
        size_bytes=len(data),
    )
    await portal.service.store.save(record, data)
    return record


@pytest.mark.parametrize("auth", [{}, {"Authorization": "Bearer wrong", "X-PDRoom-User-ID": "100"}])
async def test_secret_checked_before_discord(portal, auth):
    response = await portal.client.get("/internal/v1/status", headers=auth)
    assert response.status == 401
    assert await response.json() == {"error": "unauthorized"}
    portal.guild.fetch_member.assert_not_awaited()
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("actor", ["0", "-1", "x", "1.0", "18446744073709551616", ""])
async def test_invalid_actor_rejected(portal, actor):
    auth = headers()
    auth["X-PDRoom-User-ID"] = actor
    response = await portal.client.get("/internal/v1/status", headers=auth)
    assert response.status == 400
    portal.guild.fetch_member.assert_not_awaited()


async def test_duplicate_identity_or_body_rejected(portal):
    auth = list(headers().items()) + [("X-PDRoom-User-ID", "999")]
    response = await portal.client.get("/internal/v1/status", headers=auth)
    assert response.status == 400
    response = await portal.client.delete("/internal/v1/quotes/1000", headers=headers(), data=b"x")
    assert response.status == 400
    portal.guild.fetch_member.assert_not_awaited()


@pytest.mark.parametrize("state", ["not_ready", "closed", "missing_guild", "unavailable_guild"])
async def test_unavailable_guild_is_not_nonmember(portal, state):
    if state == "not_ready":
        portal.bot.is_ready.return_value = False
    elif state == "closed":
        portal.bot.is_closed.return_value = True
    elif state == "missing_guild":
        portal.bot.get_guild.return_value = None
    else:
        portal.guild.unavailable = True
    response = await portal.client.get("/internal/v1/status", headers=headers())
    assert response.status == 503
    assert await response.json() == {"error": "bot_unavailable"}
    portal.guild.fetch_member.assert_not_awaited()


@pytest.mark.parametrize("error,status,code", [
    (discord.NotFound(MagicMock(status=404), "gone"), 403, "member_required"),
    (discord.Forbidden(MagicMock(status=403), "forbidden"), 503, "bot_unavailable"),
    (discord.HTTPException(MagicMock(status=500), "down"), 503, "bot_unavailable"),
])
async def test_membership_errors_are_distinguished(portal, error, status, code):
    portal.guild.fetch_member.side_effect = error
    response = await portal.client.get("/internal/v1/status", headers=headers())
    assert response.status == status
    assert await response.json() == {"error": code}


async def test_member_cache_expires_and_event_invalidates(portal):
    for _ in range(2):
        assert (await portal.client.get("/internal/v1/status", headers=headers())).status == 200
    assert portal.guild.fetch_member.await_count == 1
    portal.api._members[100] = (0, member(100, portal.guild))
    assert (await portal.client.get("/internal/v1/status", headers=headers())).status == 200
    portal.api.invalidate_member(100)
    assert (await portal.client.get("/internal/v1/status", headers=headers())).status == 200
    assert portal.guild.fetch_member.await_count == 3


async def test_member_cache_is_bounded(portal):
    portal.config.member_cache_size = 2
    for uid in (100, 101, 102):
        assert (await portal.client.get("/internal/v1/status", headers=headers(uid))).status == 200
    assert list(portal.api._members) == [101, 102]
    assert len(portal.api._user_requests) == 2


async def test_delete_requires_fresh_membership_even_after_cached_read(portal):
    await save_quote(portal)
    assert (await portal.client.get("/internal/v1/status", headers=headers())).status == 200
    portal.guild.fetch_member.side_effect = discord.NotFound(MagicMock(status=404), "gone")
    response = await portal.client.delete("/internal/v1/quotes/1000", headers=headers())
    assert response.status == 403
    assert await portal.service.store.get(1000) is not None
    assert 100 not in portal.api._members


async def test_profile_contract_excludes_all_ranks(portal):
    response = await portal.client.get("/internal/v1/profile?period=year", headers=headers())
    assert response.status == 200
    result = await response.json()
    assert set(result) == {"user", "period", "stats", "accounts", "data_since"}
    assert set(result["stats"]) == {"messages", "voice_seconds", "reactions", "games"}
    assert "rank" not in str(result)
    assert result["user"]["id"] == "100"
    assert result["user"]["is_owner"] is False
    assert result["period"] == "year"
    assert result["stats"]["games"] == [{"name": "Dota 2", "seconds": 120}]
    assert result["accounts"]["dota"] == [{"id": "123", "name": "Dota name"}]
    assert result["accounts"]["faceit"][0]["id"] == "a-faceit-uuid"
    assert portal.builder.build_stats.call_args.kwargs["eligible_user_ids"] == {100}
    assert portal.builder.build_stats.call_args.kwargs["period"].scope == "year"
    assert (await (await portal.client.get("/internal/v1/status", headers=headers(999))).json())["is_owner"] is True


async def test_profile_lists_are_bounded(portal):
    portal.builder.build_stats.return_value.top_games = [("x" * 300, 1)] * 101
    portal.builder.build_accounts.return_value = ProfileAccounts(dota_ids=tuple(range(1, 102)))
    result = await (await portal.client.get("/internal/v1/profile", headers=headers())).json()
    assert len(result["stats"]["games"]) == len(result["accounts"]["dota"]) == 100
    assert len(result["stats"]["games"][0]["name"]) == 256


@pytest.mark.parametrize("path", [
    "profile?period=week", "profile?user_id=999", "profile?period=month&period=year",
    "quotes?scope=other", "quotes?sort=bad", "quotes?offset=-1", "quotes?limit=101",
    "quotes?limit=0", "quotes?offset=100001", "quotes/abc/image", "quotes/0/image",
    "quotes/18446744073709551616/image", "status?user_id=999",
])
async def test_invalid_queries_and_ids(portal, path):
    response = await portal.client.get(f"/internal/v1/{path}", headers=headers())
    assert response.status == 400


async def test_gallery_filters_creator_channel_and_guild_before_pagination(portal):
    for mid, kwargs in [
        (1000, {}), (1001, {}), (1002, {"saved_by": 200}),
        (1003, {"channel_id": 11}), (1004, {"channel_id": 12}), (1005, {"guild_id": 2}),
    ]:
        await save_quote(portal, mid, **kwargs)
    result = await (await portal.client.get("/internal/v1/quotes?limit=1", headers=headers())).json()
    assert result["total"] == 2
    assert result["next_offset"] == 1
    assert result["items"][0]["id"] == "1001"
    assert result["items"][0]["saved_by"] == "100"
    assert result["items"][0]["can_delete"] is True
    result = await (await portal.client.get("/internal/v1/quotes?sort=oldest&offset=1", headers=headers())).json()
    assert [item["id"] for item in result["items"]] == ["1001"]
    assert result["next_offset"] is None
    response = await portal.client.get("/internal/v1/quotes?scope=all", headers=headers())
    assert response.status == 403
    result = await (await portal.client.get("/internal/v1/quotes?scope=all", headers=headers(999))).json()
    assert result["total"] == 3
    assert all(item["can_delete"] for item in result["items"])


@pytest.mark.parametrize("actor,allowed", [(100, True), (999, True), (300, False), (200, False)])
async def test_creator_owner_author_and_unrelated_delete_policy(portal, actor, allowed):
    await save_quote(portal)
    response = await portal.client.delete("/internal/v1/quotes/1000", headers=headers(actor))
    assert response.status == (200 if allowed else 403)
    assert (await portal.service.store.get(1000) is None) == allowed
    if allowed:
        assert await response.json() == {"deleted": True}
        response = await portal.client.delete("/internal/v1/quotes/1000", headers=headers(actor))
        assert await response.json() == {"deleted": False}


async def test_discord_manage_messages_and_quote_author_do_not_grant_delete(portal):
    await save_quote(portal)
    for uid in (200, 300):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = portal.guild
        interaction.user.id = uid
        interaction.permissions = discord.Permissions(manage_messages=True, administrator=True)
        with pytest.raises(QuotePermissionError):
            await portal.service.delete(interaction, 1000)
    assert await portal.service.store.get(1000) is not None


async def test_image_checks_actor_and_current_channel_every_time(portal):
    await save_quote(portal)
    response = await portal.client.get("/internal/v1/quotes/1000/image", headers=headers())
    assert response.status == 200
    assert response.content_type == "image/webp"
    assert await response.read() == b"RIFF" + (12).to_bytes(4, "little") + b"WEBP" + b"testdata"
    assert (await portal.client.get("/internal/v1/quotes/1000/image", headers=headers(300))).status == 403
    portal.guild.channels[0].permissions_for.return_value = discord.Permissions.none()
    assert (await portal.client.get("/internal/v1/quotes/1000/image", headers=headers())).status == 404
    assert (await portal.client.delete("/internal/v1/quotes/1000", headers=headers())).status == 404
    assert await portal.service.store.get(1000) is not None
    assert (await portal.client.get("/internal/v1/quotes/2000/image", headers=headers())).status == 404


async def test_image_deleted_during_read_returns_not_found(portal):
    await save_quote(portal)
    read = portal.service.store.read
    async def delete_then_read(mid):
        await portal.service.store.remove(mid)
        return await read(mid)
    with patch.object(portal.service.store, "read", side_effect=delete_then_read):
        response = await portal.client.get("/internal/v1/quotes/1000/image", headers=headers())
    assert response.status == 404


@pytest.mark.parametrize("change", ["source", "owner"])
async def test_image_rechecks_privacy_and_owner_after_read(portal, change):
    await save_quote(portal)
    read = portal.service.store.read
    async def changed_during_read(mid):
        data = await read(mid)
        if change == "source":
            portal.guild.channels[0].is_nsfw.return_value = True
        else:
            portal.guild.owner_id = 500
        return data
    with patch.object(portal.service.store, "read", side_effect=changed_during_read):
        response = await portal.client.get("/internal/v1/quotes/1000/image", headers=headers(999))
    assert response.status == (404 if change == "source" else 403)


async def test_gallery_rechecks_source_after_loading_index(portal):
    await save_quote(portal)
    listing = portal.service.store.list_records
    async def changed_during_load():
        records = await listing()
        portal.guild.channels[0].is_nsfw.return_value = True
        return records
    with patch.object(portal.service.store, "list_records", side_effect=changed_during_load):
        response = await portal.client.get("/internal/v1/quotes", headers=headers())
    assert await response.json() == {"items": [], "total": 0, "next_offset": None}


async def test_gallery_rechecks_owner_after_loading_index(portal):
    await save_quote(portal)
    listing = portal.service.store.list_records
    async def changed_during_load():
        records = await listing()
        portal.guild.owner_id = 500
        return records
    with patch.object(portal.service.store, "list_records", side_effect=changed_during_load):
        response = await portal.client.get("/internal/v1/quotes?scope=all", headers=headers(999))
    assert response.status == 403


async def test_shared_writer_lock_prevents_web_delete_racing_discord_save(portal):
    await save_quote(portal)
    await portal.service._writes.acquire()
    deletion = asyncio.create_task(portal.client.delete("/internal/v1/quotes/1000", headers=headers()))
    try:
        for _ in range(100):
            if portal.guild.fetch_member.await_count:
                break
            await asyncio.sleep(0.005)
        assert portal.guild.fetch_member.await_count == 1
        assert not deletion.done()
        assert await portal.service.store.get(1000) is not None
    finally:
        portal.service._writes.release()
    assert (await deletion).status == 200
    assert await portal.service.store.get(1000) is None


async def test_concurrency_limit_returns_429_without_queue(portal):
    for _ in range(portal.config.max_concurrent):
        await portal.api._slots.acquire()
    try:
        response = await portal.client.get("/internal/v1/profile", headers=headers())
        assert response.status == 429
        assert response.headers["Retry-After"] == "60"
        portal.guild.fetch_member.assert_not_awaited()
    finally:
        for _ in range(portal.config.max_concurrent):
            portal.api._slots.release()


@pytest.mark.parametrize("global_limit", [True, False])
async def test_rate_limits_are_bounded(portal, global_limit):
    if global_limit:
        portal.config.requests_per_minute = 1
    else:
        portal.config.user_requests_per_minute = 1
    assert (await portal.client.get("/internal/v1/status", headers=headers())).status == 200
    assert (await portal.client.get("/internal/v1/status", headers=headers(101 if global_limit else 100))).status == 429
    assert portal.guild.fetch_member.await_count == 1


async def test_timeout_releases_concurrency_slot(portal):
    portal.config.request_timeout = 0.01
    async def blocked(_uid):
        await asyncio.Event().wait()
    portal.guild.fetch_member.side_effect = blocked
    assert (await portal.client.get("/internal/v1/status", headers=headers())).status == 503
    assert portal.api._slots._value == portal.config.max_concurrent


async def test_missing_or_reloading_fun_cog_fails_closed(portal):
    portal.bot.get_cog.return_value = None
    assert (await portal.client.get("/internal/v1/quotes", headers=headers())).status == 503
    portal.bot.get_cog.return_value = SimpleNamespace(quotes=portal.service)
    portal.service.closed = True
    assert (await portal.client.get("/internal/v1/quotes", headers=headers())).status == 503


def test_token_sources_and_defaults(tmp_path, monkeypatch):
    assert PortalApiConfig().enabled is False
    assert PortalApiConfig().host == "127.0.0.1"
    assert load_portal_token(PortalApiConfig(token=SecretStr(TOKEN))) == TOKEN
    token_file = tmp_path / "portal-token"
    token_file.write_text(TOKEN + "\n", encoding="ascii")
    assert load_portal_token(PortalApiConfig(token_file=token_file)) == TOKEN
    monkeypatch.setenv("PORTAL_API__ENABLED", "true")
    monkeypatch.setenv("PORTAL_API__TOKEN", TOKEN)
    settings = BotSettings(_env_file=None)
    assert settings.portal_api.enabled is True
    assert load_portal_token(settings.portal_api) == TOKEN
    assert TOKEN not in repr(settings)
    for config in [PortalApiConfig(), PortalApiConfig(token=SecretStr("short")),
                   PortalApiConfig(token=SecretStr(TOKEN), token_file=token_file),
                   PortalApiConfig(token=SecretStr("я" * 32)),
                   PortalApiConfig(token=SecretStr("a" * 32 + "\x00")),
                   PortalApiConfig(token=SecretStr("a" * 32 + "\x7f")),
                   PortalApiConfig(token=SecretStr("a" * 32 + " "))]:
        with pytest.raises(ValueError) as error:
            load_portal_token(config)
        assert TOKEN not in str(error.value)


def test_token_file_is_bounded(tmp_path):
    path = tmp_path / "too-large"
    path.write_bytes(b"x" * 1025)
    with pytest.raises(ValueError, match="прочитать"):
        load_portal_token(PortalApiConfig(token_file=path))
