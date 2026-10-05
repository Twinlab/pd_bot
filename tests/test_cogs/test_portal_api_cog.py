"""Жизненный цикл необязательного listener без запуска самого бота."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from cogs.portal_api import PortalApiCog, setup
from config.settings import PortalApiConfig


async def test_disabled_api_does_not_bind():
    bot = MagicMock(settings=SimpleNamespace(portal_api=PortalApiConfig()))
    cog = PortalApiCog(bot)
    with patch("cogs.portal_api.web.AppRunner") as runner:
        await cog.cog_load()
        await cog.cog_unload()
    runner.assert_not_called()
    assert cog.api is None


async def test_listener_setup_cleanup_and_member_invalidation():
    config = PortalApiConfig(enabled=True, token=SecretStr("x" * 32))
    bot = MagicMock(settings=SimpleNamespace(portal_api=config, guild_id=1))
    runner = MagicMock(setup=AsyncMock(), cleanup=AsyncMock())
    site = MagicMock(start=AsyncMock())
    with patch("cogs.portal_api.web.AppRunner", return_value=runner) as factory, patch(
        "cogs.portal_api.web.TCPSite", return_value=site
    ) as site_factory:
        cog = PortalApiCog(bot)
        await cog.cog_load()
        assert factory.call_args.kwargs["access_log"] is None
        site_factory.assert_called_once_with(runner, "127.0.0.1", 8091)
        site.start.assert_awaited_once()
        cog.api._members[100] = (123, MagicMock())
        value = MagicMock(id=100, guild=SimpleNamespace(id=1))
        await cog.on_member_remove(value)
        assert not cog.api._members
        cog.api._members[100] = (123, MagicMock())
        await cog.on_member_update(value, value)
        assert not cog.api._members
        await cog.cog_unload()
        runner.cleanup.assert_awaited_once()
        assert cog.api is None


async def test_failed_bind_cleans_runner():
    config = PortalApiConfig(enabled=True, token=SecretStr("x" * 32))
    bot = MagicMock(settings=SimpleNamespace(portal_api=config, guild_id=1))
    runner = MagicMock(setup=AsyncMock(), cleanup=AsyncMock())
    site = MagicMock(start=AsyncMock(side_effect=OSError("address in use")))
    with patch("cogs.portal_api.web.AppRunner", return_value=runner), patch(
        "cogs.portal_api.web.TCPSite", return_value=site
    ):
        with pytest.raises(OSError):
            await PortalApiCog(bot).cog_load()
    runner.cleanup.assert_awaited_once()


async def test_enabled_listener_requires_guild():
    bot = MagicMock(settings=SimpleNamespace(portal_api=PortalApiConfig(enabled=True), guild_id=None))
    with pytest.raises(ValueError, match="ID"):
        await PortalApiCog(bot).cog_load()


async def test_setup_registers_cog():
    bot = MagicMock(add_cog=AsyncMock())
    await setup(bot)
    assert isinstance(bot.add_cog.call_args.args[0], PortalApiCog)
