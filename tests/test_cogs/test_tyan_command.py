"""Discord-выдача /tyan: регистрация, ответ и сохранение при повторе."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import yaml
from discord.ext import commands
from tortoise import Tortoise

from cogs.fun import FunCog
from config.settings import FunConfig
from utils.models import TyanRoll
from utils.tyan.config import TyanConfig


@pytest.fixture
async def tyan_cog(mock_bot, mock_context):
    await Tortoise.init(
        db_url="sqlite://:memory:", modules={"models": ["utils.models"]}, use_tz=False
    )
    sql = (Path(__file__).parents[2] / "ops/migrations/20260910_tyan.sql").read_text(
        encoding="utf-8"
    )
    await Tortoise.get_connection("default").execute_script(sql)
    mock_bot.settings.fun = FunConfig(tyan=TyanConfig(mother_chance=0, none_chance=0))
    mock_context.interaction = None
    mock_context.defer = AsyncMock()
    mock_context.guild.members = [
        SimpleNamespace(id=mock_context.author.id, bot=False),
        SimpleNamespace(id=2, bot=False),
        SimpleNamespace(id=3, bot=True),
    ]
    yield FunCog(mock_bot)
    await Tortoise.close_connections()


def test_tyan_is_guild_only_hybrid_without_reroll_parameters():
    command = FunCog.tyan
    assert isinstance(command, commands.HybridCommand)
    assert command.app_command.guild_only
    assert command.clean_params == {}


async def test_prefix_check_rejects_dm(mock_context):
    mock_context.guild = None
    with pytest.raises(commands.NoPrivateMessage):
        for predicate in FunCog.tyan.checks:
            await discord.utils.maybe_coroutine(predicate, mock_context)


@pytest.mark.parametrize("slash", [False, True])
async def test_command_sends_saved_card_and_defers_slash(tyan_cog, mock_context, slash):
    mock_context.interaction = MagicMock() if slash else None

    async def ensure_acknowledged(*args, **kwargs):
        if slash:
            mock_context.defer.assert_awaited()
        return await original(*args, **kwargs)

    original = tyan_cog.tyan_manager.get_daily_roll
    with patch.object(tyan_cog.tyan_manager, "get_daily_roll", side_effect=ensure_acknowledged):
        await tyan_cog.tyan.callback(tyan_cog, mock_context)
        await tyan_cog.tyan.callback(tyan_cog, mock_context)
    calls = mock_context.send.await_args_list
    assert len(calls) == 2
    first = calls[0].kwargs["embed"]
    second = calls[1].kwargs["embed"]
    assert first.to_dict() == second.to_dict()
    assert mock_context.author.display_name in first.author.name
    assert "00:00 МСК" in first.footer.text
    assert calls[0].kwargs["ephemeral"] is False
    assert await TyanRoll.all().count() == 1
    if not slash:
        mock_context.defer.assert_not_awaited()


async def test_mother_targets_human_other_than_author(tyan_cog, mock_context):
    tyan_cog.bot.settings.fun.tyan = TyanConfig(mother_chance=1, none_chance=0)
    await tyan_cog.tyan.callback(tyan_cog, mock_context)
    row = await TyanRoll.get(discord_user_id=mock_context.author.id)
    assert row.kind == "mother"
    assert row.target_user_id == 2
    assert mock_context.send.await_args.kwargs["embed"].description == (
        "тебе досталась мать <@2>"
    )
    assert mock_context.send.await_args.kwargs["content"] is None


async def test_solo_user_with_bots_gets_normal_roll(tyan_cog, mock_context):
    tyan_cog.bot.settings.fun.tyan = TyanConfig(mother_chance=1, none_chance=0)
    mock_context.guild.members = [member for member in mock_context.guild.members if member.id != 2]
    await tyan_cog.tyan.callback(tyan_cog, mock_context)
    assert (await TyanRoll.get(discord_user_id=mock_context.author.id)).kind == "normal"


async def test_failed_discord_send_keeps_roll_for_retry(tyan_cog, mock_context):
    mock_context.send.side_effect = RuntimeError("Discord unavailable")
    await tyan_cog.tyan.callback(tyan_cog, mock_context)
    first = mock_context.send.await_args.kwargs["embed"]
    mock_context.send.side_effect = None
    await tyan_cog.tyan.callback(tyan_cog, mock_context)
    assert mock_context.send.await_args.kwargs["embed"].to_dict() == first.to_dict()
    assert await TyanRoll.all().count() == 1


async def test_database_failure_uses_shared_error_handler(tyan_cog, mock_context):
    mock_context.command = tyan_cog.tyan
    with (
        patch.object(tyan_cog.tyan_manager, "get_daily_roll", side_effect=RuntimeError("DB failure")),
        patch("utils.error_handler.safe_send_error", new_callable=AsyncMock) as send_error,
    ):
        await tyan_cog.tyan.callback(tyan_cog, mock_context)
    send_error.assert_awaited_once()
    mock_context.send.assert_not_awaited()
    assert await TyanRoll.all().count() == 0


async def test_direct_dm_callback_does_not_write(tyan_cog, mock_context):
    mock_context.guild = None
    await tyan_cog.tyan.callback(tyan_cog, mock_context)
    assert await TyanRoll.all().count() == 0
    assert mock_context.send.await_args.kwargs["ephemeral"] is True


def test_repository_yaml_loads_tyan_settings_without_secrets():
    path = Path(__file__).parents[2] / "config/bot_settings.yaml"
    config = FunConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))["fun"])
    assert config.tyan == TyanConfig()


async def test_bot_registers_tyan_in_tree_and_fun_help():
    from cogs.help import build_help_catalog

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    try:
        await bot.add_cog(FunCog(bot))
        command = bot.tree.get_command("tyan")
        assert command is not None
        assert bot.get_command("tyan") is not None
        catalog = build_help_catalog(bot.tree.get_commands())
        assert any(entry.name == "tyan" for entry in catalog["Развлечения"])
    finally:
        await bot.close()
