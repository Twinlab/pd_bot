"""Интеграционные границы цитат: публичность, запись и жизненный цикл кнопок."""

import asyncio
import re
import threading
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from config.settings import QuotesConfig
from utils.quotes.service import QuoteService
from utils.quotes.store import QuoteStore
from utils.quotes.views import (
    DeleteQuoteButton,
    QuoteActionsView,
    QuoteDeleteConfirmView,
    QuotePreviewView,
)

CARD_BYTES = b"RIFF-test-card-WEBP"


def make_channel(channel_id: int, *, public: bool = True, nsfw: bool = False) -> MagicMock:
    """Канал с правами, читаемыми настоящим public_message_channel_ids."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = "общий"
    channel.permissions_for.return_value = discord.Permissions(
        view_channel=public, read_message_history=public
    )
    channel.overwrites = {}
    channel.is_nsfw.return_value = nsfw
    channel.fetch_message = AsyncMock()
    return channel


@pytest.fixture
def guild() -> MagicMock:
    """Один сервер: никаких запросов реальной гильдии или её истории."""
    value = MagicMock(spec=discord.Guild)
    value.id = 1
    channel = make_channel(10)
    value.channels = [channel]
    value.threads = []
    value.get_channel_or_thread.side_effect = lambda cid: next(
        (channel for channel in [*value.channels, *value.threads] if channel.id == cid), None
    )
    return value


def make_interaction(guild: MagicMock | None, user_id: int = 100) -> MagicMock:
    """Интеракция с явными async callbacks и текущими правами пользователя."""
    value = MagicMock(spec=discord.Interaction)
    value.guild = guild
    value.guild_id = guild.id if guild else None
    value.user.id = user_id
    value.permissions = discord.Permissions.none()
    value.response.defer = AsyncMock()
    value.response.send_message = AsyncMock()
    value.response.edit_message = AsyncMock()
    value.edit_original_response = AsyncMock()
    return value


@pytest.fixture
def interaction(guild: MagicMock) -> MagicMock:
    return make_interaction(guild)


@pytest.fixture
def message(guild: MagicMock) -> MagicMock:
    """Обычная цитата человека с оригинальным и раскрытым текстом упоминания."""
    value = MagicMock(spec=discord.Message)
    value.id = 1000
    value.guild = guild
    value.channel = guild.channels[0]
    value.author = MagicMock(spec=discord.Member)
    value.author.id = 300
    value.author.bot = False
    value.author.name = "author"
    value.author.display_name = "Автор"
    value.created_at = datetime(2026, 10, 5, 12, tzinfo=UTC)
    value.content = "Привет <@100> <:party:123>"
    value.clean_content = "Привет @Друг <:party:123>"
    value.webhook_id = None
    value.is_system.return_value = False
    value.channel.fetch_message.return_value = value
    return value


@pytest.fixture
def service(tmp_path) -> QuoteService:
    """Настоящее хранилище ограничено уникальной pytest-папкой."""
    config = QuotesConfig(generated_path=str(tmp_path / "quotes"), min_free_bytes=0)
    store = QuoteStore(
        tmp_path / "quotes",
        max_total_bytes=config.max_total_bytes,
        max_card_bytes=config.max_card_bytes,
        min_free_bytes=0,
    )
    return QuoteService(config, 1, store=store)


@pytest.fixture
def rendering(service: QuoteService):
    """Сеть аватаров и Pillow заменены, но вся проверка/запись остаётся настоящей."""
    with (
        patch.object(service, "_avatar", new=AsyncMock(return_value=b"avatar")) as avatar,
        patch("utils.quotes.service.render_quote_card", return_value=CARD_BYTES) as render,
    ):
        yield avatar, render


@pytest.fixture
def error_reply():
    """Изолирует транспорт уже отдельно проверенного safe_send_error."""
    with (
        patch("utils.quotes.views.safe_send_error", new=AsyncMock()) as view_error,
        patch("utils.quotes.service.safe_send_error", new=AsyncMock()) as service_error,
    ):
        yield view_error, service_error


def test_public_channels_uses_current_permissions_and_excludes_nsfw(
    service: QuoteService, guild: MagicMock
) -> None:
    """Изменённые права, закрытая история, ветки и NSFW проверяются заново."""
    public = guild.channels[0]
    hidden = make_channel(20, public=False)
    nsfw = make_channel(30, nsfw=True)
    denied_role = make_channel(40)
    denied_role.overwrites = {object(): discord.PermissionOverwrite(view_channel=False)}
    thread = MagicMock(spec=discord.Thread)
    thread.id, thread.parent_id = 11, public.id
    thread.is_private.return_value = False
    thread.is_nsfw.return_value = False
    private_thread = MagicMock(spec=discord.Thread)
    private_thread.id, private_thread.parent_id = 12, public.id
    private_thread.is_private.return_value = True
    private_thread.is_nsfw.return_value = False
    guild.channels.extend([hidden, nsfw, denied_role])
    guild.threads = [thread, private_thread]

    assert service.public_channels(guild) == {10, 11}
    public.permissions_for.return_value.read_message_history = False
    assert service.public_channels(guild) == set()
    assert service.public_channels(None) == set()
    guild.id = 2
    assert service.public_channels(guild) == set()


async def test_prepare_is_ram_only_and_normalizes_display_content(
    service, interaction, message, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    avatar, render = rendering
    assert pending.image == CARD_BYTES
    assert pending.original_content == message.content
    assert pending.display_content == "Привет @Друг :party:"
    assert pending.record.author_id == message.author.id
    assert pending.record.saved_by == interaction.user.id
    assert pending.record.size_bytes == len(CARD_BYTES)
    assert not service.store.root.exists()
    assert await service.store.list_records() == []
    assert not service.store.root.exists()
    avatar.assert_awaited_once_with(message.author)
    card, raw_avatar = render.call_args.args
    assert card.text == pending.display_content
    assert card.display_name == "Автор"
    assert raw_avatar == b"avatar"
    assert render.call_args.kwargs["max_bytes"] == service.config.max_card_bytes


@pytest.mark.parametrize("kind", ["bot", "webhook", "system"])
async def test_source_must_be_an_ordinary_human_message(
    service, interaction, message, rendering, kind
) -> None:
    if kind == "bot":
        message.author.bot = True
    elif kind == "webhook":
        message.webhook_id = 123
    else:
        message.is_system.return_value = True
    with pytest.raises(ValueError, match="участника"):
        await service.prepare(interaction, message)
    rendering[0].assert_not_awaited()
    rendering[1].assert_not_called()
    assert not service.store.root.exists()


async def test_commit_refetches_and_deduplicates_real_store(
    service, interaction, message, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    assert await service.commit(interaction, pending) is True
    assert await service.commit(interaction, pending) is False
    assert message.channel.fetch_message.await_count == 2
    message.channel.fetch_message.assert_awaited_with(message.id)
    assert await service.store.read(message.id) == CARD_BYTES
    assert await service.store.list_records() == [pending.record]
    assert {path.name for path in service.store.root.iterdir()} == {"1000.webp", "index.json"}


@pytest.mark.parametrize(
    "change", ["raw", "display", "author", "deleted", "forbidden", "private", "nsfw"]
)
async def test_commit_rechecks_source_and_rejects_stale_preview(
    service, interaction, message, rendering, change
) -> None:
    pending = await service.prepare(interaction, message)
    if change == "raw":
        message.content += "!"
    elif change == "display":
        message.clean_content += "!"
    elif change == "author":
        message.author.id += 1
    elif change in ("deleted", "forbidden"):
        error = discord.NotFound if change == "deleted" else discord.Forbidden
        message.channel.fetch_message.side_effect = error(MagicMock(status=404), "unavailable")
    elif change == "private":
        message.channel.permissions_for.return_value.view_channel = False
    else:
        message.channel.is_nsfw.return_value = True
    with pytest.raises(ValueError):
        await service.commit(interaction, pending)
    assert not service.store.root.exists()
    assert await service.store.get(message.id) is None


async def test_commit_rejects_other_user_before_fetch(
    service, interaction, message, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    interaction.user.id = 999
    with pytest.raises(ValueError, match="другому участнику"):
        await service.commit(interaction, pending)
    message.channel.fetch_message.assert_not_awaited()
    assert not service.store.root.exists()


async def test_visible_records_and_send_recheck_current_channel_access(
    service, interaction, message, rendering, guild
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    assert await service.visible_records(guild) == [pending.record]
    message.channel.is_nsfw.return_value = True
    assert await service.visible_records(guild) == []
    ctx = MagicMock()
    ctx.guild = guild
    ctx.send = AsyncMock()
    with pytest.raises(ValueError, match="общедоступен"):
        await service.send_record(ctx, pending.record)
    ctx.send.assert_not_awaited()
    message.channel.is_nsfw.return_value = False
    await service.send_record(ctx, pending.record)
    sent = ctx.send.call_args.kwargs
    assert isinstance(sent["view"], QuoteActionsView)
    assert sent["file"].fp.read() == CARD_BYTES
    assert sent["allowed_mentions"].to_dict() == {"parse": []}


async def test_prepare_keeps_worker_slot_until_repeated_cancellation_finishes(
    service, interaction, message
) -> None:
    """Повторная отмена не освобождает слот ещё работающего Pillow-потока."""
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def render(*_args, **_kwargs):
        entered.set()
        try:
            assert release.wait(5), "worker was not released"
            return CARD_BYTES
        finally:
            finished.set()

    with (
        patch.object(service, "_avatar", new=AsyncMock(return_value=None)),
        patch("utils.quotes.service.render_quote_card", side_effect=render),
    ):
        preparing = asyncio.create_task(service.prepare(interaction, message))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            preparing.cancel()
            await asyncio.sleep(0)
            preparing.cancel()
            # Отмена проходит через несколько Task: одного yield недостаточно,
            # чтобы ошибочное освобождение semaphore успело проявиться.
            await asyncio.wait({preparing}, timeout=0.02)
            assert not preparing.done()
            assert service._render_slots._value == 1
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await preparing
            assert await asyncio.to_thread(finished.wait, 2)
    assert service._render_slots._value == 2
    assert not service.store.root.exists()


async def test_start_preview_is_private_and_saves_only_on_button(
    service, interaction, message, rendering
) -> None:
    await service.start_preview(interaction, message)
    view = service.previews[interaction.user.id]
    assert isinstance(view, QuotePreviewView)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    sent = interaction.edit_original_response.call_args.kwargs
    assert sent["view"] is view
    assert sent["attachments"][0].fp.read() == CARD_BYTES
    assert not service.store.root.exists()
    await view.save.callback(interaction)
    assert await service.store.read(message.id) == CARD_BYTES
    assert view.pending is None
    assert not service.previews
    assert interaction.edit_original_response.call_args.kwargs["attachments"] == []


async def test_unauthorized_preview_save_and_cancel_keep_owner_state(
    service, interaction, message, rendering, error_reply, guild
) -> None:
    await service.start_preview(interaction, message)
    view = service.previews[interaction.user.id]
    intruder = make_interaction(guild, 999)
    await view.save.callback(intruder)
    await view.cancel.callback(intruder)
    assert view.pending is not None
    assert service.previews[100] is view
    assert error_reply[0].await_count == 2
    intruder.response.defer.assert_not_awaited()
    assert not service.store.root.exists()
    await view.expire()


@pytest.mark.parametrize("change", ["changed", "deleted", "private"])
async def test_preview_save_refetches_source_before_writing(
    service, interaction, message, rendering, change
) -> None:
    """Кнопка Save не обходит повторную проверку источника самим сервисом."""
    await service.start_preview(interaction, message)
    view = service.previews[interaction.user.id]
    if change == "changed":
        message.content += " изменено"
    elif change == "deleted":
        message.channel.fetch_message.side_effect = discord.NotFound(MagicMock(status=404), "gone")
    else:
        message.channel.permissions_for.return_value.read_message_history = False
    with pytest.raises(ValueError):
        await view.save.callback(interaction)
    message.channel.fetch_message.assert_awaited_once_with(message.id)
    assert not service.store.root.exists()
    await view.expire()


async def test_replacing_preview_releases_previous_card(
    service, interaction, message, rendering
) -> None:
    """Один пользователь не оставляет несколько живых карточек в памяти."""
    await service.start_preview(interaction, message)
    previous = service.previews[interaction.user.id]
    await service.start_preview(interaction, message)
    current = service.previews[interaction.user.id]
    assert current is not previous
    assert current.pending is not None
    assert previous.pending is None
    assert previous.is_finished()
    previous.release()
    assert service.previews[interaction.user.id] is current
    assert len(service.previews) == 1
    await current.expire()


async def test_failed_preview_delivery_releases_card(
    service, interaction, message, rendering
) -> None:
    """Сбой Discord после рендера не удерживает байты и квоту предпросмотров."""
    interaction.edit_original_response.side_effect = discord.HTTPException(
        MagicMock(status=500), "down"
    )
    with pytest.raises(discord.HTTPException):
        await service.start_preview(interaction, message)
    failed = interaction.edit_original_response.call_args.kwargs["view"]
    assert failed.pending is None
    assert failed.is_finished()
    assert not service.previews
    assert not service._preparing
    assert not service.store.root.exists()


@pytest.mark.parametrize("close", ["timeout", "cancel", "expired_click", "service_close"])
async def test_preview_end_releases_bytes_and_removes_attachment(
    service, interaction, message, rendering, error_reply, close
) -> None:
    await service.start_preview(interaction, message)
    view = service.previews[interaction.user.id]
    if close == "timeout":
        await view.on_timeout()
    elif close == "cancel":
        await view.cancel.callback(interaction)
    elif close == "expired_click":
        view.deadline = 0
        await view.save.callback(interaction)
    else:
        await service.close()
    assert view.pending is None
    assert view.is_finished()
    assert not service.previews
    assert interaction.edit_original_response.call_args.kwargs["attachments"] == []
    assert interaction.edit_original_response.call_args.kwargs["view"] is None
    assert not service.store.root.exists()


async def test_preview_timeout_releases_bytes_when_discord_message_is_gone(
    service, interaction, message, rendering
) -> None:
    await service.start_preview(interaction, message)
    view = service.previews[interaction.user.id]
    interaction.edit_original_response.side_effect = discord.NotFound(MagicMock(status=404), "gone")
    await view.on_timeout()
    assert view.pending is None
    assert not service.previews
    assert not service.store.root.exists()


async def test_concurrent_preview_saves_do_not_duplicate_or_retain_card(
    service, interaction, message, rendering, error_reply
) -> None:
    await service.start_preview(interaction, message)
    view = service.previews[interaction.user.id]
    await asyncio.gather(view.save.callback(interaction), view.save.callback(interaction))
    assert len(await service.store.list_records()) == 1
    assert view.pending is None
    assert not service.previews


async def test_duplicate_preview_does_not_render_again(
    service, interaction, message, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    rendering[1].reset_mock()
    await service.start_preview(interaction, message)
    rendering[1].assert_not_called()
    assert not service.previews
    sent = interaction.edit_original_response.call_args.kwargs
    assert "Дубликат" in sent["content"]
    assert isinstance(sent["view"], QuoteActionsView)


async def test_unauthorized_dynamic_delete_does_not_open_confirmation(
    service, interaction, message, rendering, error_reply
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    interaction.client.get_cog.return_value = MagicMock(quotes=service)
    await DeleteQuoteButton(message.id).callback(interaction)
    assert await service.store.get(message.id) == pending.record
    interaction.edit_original_response.assert_not_awaited()
    assert "автор или модератор" in error_reply[1].call_args.args[1]


async def test_delete_confirmation_rechecks_current_permissions(
    service, interaction, message, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    interaction.permissions.manage_messages = True
    assert await service.removable(interaction, message.id) == pending.record
    view = QuoteDeleteConfirmView(service, interaction, message.id)
    interaction.permissions.manage_messages = False
    with pytest.raises(ValueError, match="автор или модератор"):
        await view.confirm.callback(interaction)
    assert await service.store.get(message.id) == pending.record
    interaction.permissions.manage_messages = True
    await view.confirm.callback(interaction)
    assert await service.store.get(message.id) is None
    assert view.is_finished()
    assert (
        "Ранее отправленные копии" in interaction.edit_original_response.call_args.kwargs["content"]
    )


async def test_delete_confirmation_cannot_be_taken_over(
    service, interaction, message, rendering, error_reply, guild
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    author = make_interaction(guild, message.author.id)
    view = QuoteDeleteConfirmView(service, author, message.id)
    intruder = make_interaction(guild, 999)
    intruder.permissions.manage_messages = True
    await view.confirm.callback(intruder)
    assert await service.store.get(message.id) == pending.record
    error_reply[0].assert_awaited_once()
    await view.confirm.callback(author)
    assert await service.store.get(message.id) is None


async def test_dynamic_item_rebuild_resolves_fresh_service_after_restart(
    service, interaction, message, rendering, guild
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    service.closed = True
    fresh = QuoteService(service.config, 1, store=QuoteStore(service.store.root, min_free_bytes=0))
    author = make_interaction(guild, message.author.id)
    author.client.get_cog.return_value = MagicMock(quotes=fresh)
    custom_id = f"quote:delete:{message.id}"
    item = discord.ui.Button(custom_id=custom_id)
    match = re.fullmatch(DeleteQuoteButton.__discord_ui_compiled_template__, custom_id)
    assert match is not None
    rebuilt = await DeleteQuoteButton.from_custom_id(author, item, match)
    await rebuilt.callback(author)
    author.client.get_cog.assert_called_once_with("FunCog")
    author.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    confirmation = author.edit_original_response.call_args.kwargs["view"]
    assert isinstance(confirmation, QuoteDeleteConfirmView)
    assert confirmation.service is fresh
    await confirmation.confirm.callback(author)
    assert await fresh.store.get(message.id) is None
