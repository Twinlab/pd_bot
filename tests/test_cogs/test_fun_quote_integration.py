"""Регистрация цитат в настоящем Bot и совместная выдача старой/новой коллекции."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from cogs.fun import FunCog
from config.settings import BotSettings
from utils.quotes.store import QuoteRecord
from utils.quotes.views import DeleteQuoteButton

CARD = b"generated-quote-webp"


def make_channel(channel_id: int, *, public: bool = True, nsfw: bool = False) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.permissions_for.return_value = discord.Permissions(
        view_channel=public, read_message_history=public
    )
    channel.overwrites = {}
    channel.is_nsfw.return_value = nsfw
    return channel


@pytest.fixture
def guild() -> MagicMock:
    value = MagicMock(spec=discord.Guild)
    value.id = 1
    value.channels = [make_channel(10), make_channel(20, public=False), make_channel(30, nsfw=True)]
    value.threads = []
    value.get_channel_or_thread.side_effect = lambda cid: next(
        (channel for channel in value.channels if channel.id == cid), None
    )
    return value


@pytest.fixture
async def cog(tmp_path):
    """Реальный Bot и дерево команд, без login/start, БД и каталога runtime quotes."""
    settings = BotSettings(_env_file=None)
    settings.guild_id = 1
    settings.fun.quotes.generated_path = str(tmp_path / "quotes")
    settings.fun.quotes.min_free_bytes = 0
    with patch("cogs.fun.get_settings", return_value=settings):
        async with commands.Bot(command_prefix="!", intents=discord.Intents.none()) as bot:
            bot.settings = settings
            value = FunCog(bot)
            await bot.add_cog(value)
            yield value


@pytest.fixture
def legacy():
    """Старую коллекцию представляет только её API, файлы assets не открываются."""
    with (
        patch("cogs.fun.scan_quotes_folders", return_value=[]) as scan,
        patch("cogs.fun.send_random_quote_image", new=AsyncMock()) as send,
        patch("cogs.fun.safe_send_error", new=AsyncMock()) as error,
    ):
        yield scan, send, error


@pytest.fixture
def ctx(cog: FunCog, guild: MagicMock) -> MagicMock:
    value = MagicMock(spec=commands.Context)
    value.guild = guild
    value.channel = guild.channels[0]
    value.author.id = 100
    value.command = cog.quote
    value.interaction = None
    value.send = AsyncMock()
    return value


async def add_record(
    cog: FunCog,
    message_id: int = 1000,
    *,
    author_id: int = 300,
    name: str = "author",
    display: str = "Автор",
    channel_id: int = 10,
) -> QuoteRecord:
    """Создаёт запись настоящего QuoteStore только во временной папке теста."""
    now = datetime(2026, 10, 5, tzinfo=UTC)
    record = QuoteRecord(
        message_id=message_id,
        guild_id=1,
        channel_id=channel_id,
        author_id=author_id,
        author_name=name,
        author_display_name=display,
        created_at=now,
        saved_by=100,
        saved_at=now + timedelta(seconds=message_id),
        size_bytes=len(CARD),
    )
    await cog.quotes.store.save(record, CARD)
    return record


async def test_load_unload_registers_menu_and_dynamic_controls_offline(cog: FunCog) -> None:
    """Живое дерево получает и теряет меню/динамический обработчик вместе с когом."""
    bot = cog.bot
    menu = bot.tree.get_command("В цитаты", type=discord.AppCommandType.message)
    assert menu is cog.quote_menu
    assert isinstance(menu, app_commands.ContextMenu)
    assert DeleteQuoteButton in bot._connection._view_store._dynamic_items.values()
    service = cog.quotes
    assert not service.store.root.exists()

    await bot.remove_cog("FunCog")

    assert bot.tree.get_command("В цитаты", type=discord.AppCommandType.message) is None
    assert DeleteQuoteButton not in bot._connection._view_store._dynamic_items.values()
    assert service.closed
    assert not service.store.root.exists()
    replacement = FunCog(bot)
    await bot.add_cog(replacement)
    assert (
        bot.tree.get_command("В цитаты", type=discord.AppCommandType.message)
        is replacement.quote_menu
    )


async def test_unload_removes_configured_guild_copy_after_global_clear(cog: FunCog) -> None:
    """Локальная схема production sync не оставляет callback выгруженного кога."""
    bot = cog.bot
    target = discord.Object(id=1)
    service = cog.quotes
    with patch.object(bot.tree, "sync", new=AsyncMock()) as sync:
        bot.tree.copy_global_to(guild=target)
        bot.tree.clear_commands(guild=None)
        assert (
            bot.tree.get_command("В цитаты", guild=target, type=discord.AppCommandType.message)
            is cog.quote_menu
        )
        await bot.remove_cog("FunCog")
        assert (
            bot.tree.get_command("В цитаты", guild=target, type=discord.AppCommandType.message)
            is None
        )
        assert DeleteQuoteButton not in bot._connection._view_store._dynamic_items.values()
        assert service.closed
        sync.assert_not_awaited()


async def test_unload_does_not_remove_replaced_guild_menu(cog: FunCog) -> None:
    """Старый ког не удаляет из дерева уже установленный новый экземпляр меню."""
    bot = cog.bot
    target = discord.Object(id=1)
    bot.tree.copy_global_to(guild=target)
    bot.tree.clear_commands(guild=None)
    replacement = FunCog(bot)
    bot.tree.add_command(replacement.quote_menu, guild=target, override=True)
    await bot.remove_cog("FunCog")
    assert (
        bot.tree.get_command("В цитаты", guild=target, type=discord.AppCommandType.message)
        is replacement.quote_menu
    )


async def test_menu_is_guild_only_and_cooldown_is_per_member(cog: FunCog, guild: MagicMock) -> None:
    """Меню доступно обычному участнику; частые вызовы ограничены отдельно для каждого."""
    menu = cog.quote_menu
    payload = menu.to_dict(cog.bot.tree)
    assert payload["type"] == discord.AppCommandType.message.value
    assert payload["dm_permission"] is False
    assert payload["default_member_permissions"] is None
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user.id = 100
    interaction.permissions = discord.Permissions.none()
    interaction.created_at = datetime(2026, 10, 5, tzinfo=UTC)
    assert await menu._check_can_run(interaction)
    with pytest.raises(app_commands.CommandOnCooldown) as caught:
        await menu._check_can_run(interaction)
    assert 0 < caught.value.retry_after <= 30
    interaction.user.id = 200
    assert await menu._check_can_run(interaction)


async def test_explicit_user_id_sends_generated_card(cog: FunCog, ctx, legacy) -> None:
    record = await add_record(cog)
    await cog.quote.callback(cog, ctx, f"user:{record.author_id}")
    sent = ctx.send.call_args.kwargs
    assert sent["file"].filename == f"quote-{record.message_id}.webp"
    assert sent["file"].fp.read() == CARD
    legacy[1].assert_not_awaited()
    legacy[2].assert_not_awaited()


@pytest.mark.parametrize("message_id", [1000, 1001])
async def test_explicit_id_keeps_author_identity_through_renames_and_reused_names(
    cog: FunCog, ctx, legacy, message_id: int
) -> None:
    """user:ID объединяет историю автора, но не другого человека с прежним ником."""
    before = await add_record(cog, 1000, name="shared")
    after = await add_record(cog, 1001, name="renamed")
    await add_record(cog, 1002, author_id=400, name="shared", display="Другой участник")
    legacy[0].return_value = ["shared"]
    selected = before if message_id == before.message_id else after
    with patch("cogs.fun.random.choice", return_value=selected) as choose:
        await cog.quote.callback(cog, ctx, "user:300")
    candidates = choose.call_args.args[0]
    assert {record.message_id for record in candidates} == {1000, 1001}
    assert {record.author_id for record in candidates} == {300}
    assert ctx.send.call_args.kwargs["file"].filename == f"quote-{message_id}.webp"
    legacy[1].assert_not_awaited()


@pytest.mark.parametrize("use_legacy", [False, True])
async def test_named_legacy_group_can_return_old_or_new_card(
    cog: FunCog, ctx, legacy, use_legacy
) -> None:
    """Выбор старой папки продолжает работать и включает новые цитаты того же имени."""
    record = await add_record(cog, name="author")
    legacy[0].return_value = ["Author"]
    with patch("cogs.fun.random.choice", return_value=None if use_legacy else record) as choose:
        await cog.quote.callback(cog, ctx, "Author")
    assert record in choose.call_args.args[0]
    assert None in choose.call_args.args[0]
    if use_legacy:
        legacy[1].assert_awaited_once_with(ctx, "Author", embed=False)
        ctx.send.assert_not_awaited()
    else:
        assert ctx.send.call_args.kwargs["file"].filename == "quote-1000.webp"
        legacy[1].assert_not_awaited()


@pytest.mark.parametrize("selected", ["archive", "user:300"])
async def test_random_default_includes_both_collections(
    cog: FunCog, ctx, legacy, selected: str
) -> None:
    record = await add_record(cog)
    legacy[0].return_value = ["archive"]

    def choose(items):
        return selected if selected in items else items[0]

    with patch("cogs.fun.random.choice", side_effect=choose) as choice:
        await cog.quote.callback(cog, ctx, None)
    assert set(choice.call_args_list[0].args[0]) == {"archive", "user:300"}
    if selected == "archive":
        legacy[1].assert_awaited_once_with(ctx, "archive", embed=False)
        ctx.send.assert_not_awaited()
    else:
        assert ctx.send.call_args.kwargs["file"].filename == f"quote-{record.message_id}.webp"
        legacy[1].assert_not_awaited()


async def test_hidden_author_id_never_falls_back_to_legacy(cog: FunCog, ctx, legacy) -> None:
    await add_record(cog, channel_id=20)
    legacy[0].return_value = ["author"]
    await cog.quote.callback(cog, ctx, "user:300")
    ctx.send.assert_not_awaited()
    legacy[1].assert_not_awaited()
    legacy[2].assert_awaited_once()


async def test_autocomplete_contains_only_visible_generated_authors_and_latest_name(
    cog: FunCog, guild: MagicMock, legacy
) -> None:
    """Подсказки скрывают private/NSFW источники и показывают последний сохранённый ник."""
    await add_record(cog, 1000, name="old_name", display="Старый ник")
    await add_record(cog, 1001, name="new_name", display="Новый ник")
    await add_record(cog, 1002, author_id=400, name="secret", display="Секрет", channel_id=20)
    await add_record(cog, 1003, author_id=500, name="adult", display="NSFW", channel_id=30)
    legacy[0].return_value = ["archive"]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    result = await cog.quote_autocomplete(interaction, "")
    assert {choice.value for choice in result} == {"archive", "user:300"}
    assert (
        next(choice.name for choice in result if choice.value == "user:300")
        == "Новый ник (@new_name)"
    )
    assert await cog.quote_autocomplete(interaction, "СЕКРЕТ") == []
    matching = await cog.quote_autocomplete(interaction, "НОВЫЙ")
    assert [choice.value for choice in matching] == ["user:300"]

    guild.channels[0].permissions_for.return_value.read_message_history = False
    remaining = await cog.quote_autocomplete(interaction, "")
    assert [choice.value for choice in remaining] == ["archive"]
