"""Перезагрузка цитат дожидается записи, а отмена не оставляет занятых preview."""

import asyncio
from unittest.mock import MagicMock, patch

import discord
import pytest

from tests.test_utils.test_quote_service import (
    CARD_BYTES,
    make_interaction,
)
from tests.test_utils.test_quote_service import (
    guild as guild,
)
from tests.test_utils.test_quote_service import (
    interaction as interaction,
)
from tests.test_utils.test_quote_service import (
    message as message,
)
from tests.test_utils.test_quote_service import (
    rendering as rendering,
)
from tests.test_utils.test_quote_service import (
    service as service,
)
from utils.quotes.service import QuoteService
from utils.quotes.views import QuoteDeleteConfirmView


async def test_cancelled_preview_delivery_releases_bytes_and_capacity(
    service: QuoteService, interaction: MagicMock, message: MagicMock, rendering
) -> None:
    service.config.max_pending_previews = 1
    entered = asyncio.Event()

    async def blocked_edit(**kwargs: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    interaction.edit_original_response.side_effect = blocked_edit
    preparing = asyncio.create_task(service.start_preview(interaction, message))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        view = service.previews[interaction.user.id]
    finally:
        preparing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await preparing
    assert view.pending is None
    assert view.is_finished()
    assert not service.previews
    assert not service._preparing
    assert not service.store.root.exists()

    fresh = make_interaction(interaction.guild, interaction.user.id)
    await service.start_preview(fresh, message)
    assert service.previews[interaction.user.id].pending is not None
    await service.close()


async def test_owner_can_replace_preview_when_capacity_is_full(
    service: QuoteService, interaction: MagicMock, message: MagicMock, rendering
) -> None:
    service.config.max_pending_previews = 1
    await service.start_preview(interaction, message)
    previous = service.previews[interaction.user.id]
    fresh = make_interaction(interaction.guild, interaction.user.id)
    await service.start_preview(fresh, message)
    assert service.previews[interaction.user.id] is not previous
    assert previous.pending is None
    assert previous.is_finished()
    assert len(service.previews) == 1

    other = make_interaction(interaction.guild, interaction.user.id + 1)
    with pytest.raises(ValueError, match="много предпросмотров"):
        await service.start_preview(other, message)
    other.response.defer.assert_not_awaited()
    await service.close()


async def test_close_waits_for_save_and_rejects_subsequent_commits(
    service: QuoteService, interaction: MagicMock, message: MagicMock, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    entered = asyncio.Event()
    release = asyncio.Event()
    original_save = service.store.save

    async def slow_save(record, data: bytes) -> bool:
        entered.set()
        await release.wait()
        return await original_save(record, data)

    with patch.object(service.store, "save", side_effect=slow_save) as saving:
        write = asyncio.create_task(service.commit(interaction, pending))
        await asyncio.wait_for(entered.wait(), timeout=2)
        closing = asyncio.create_task(service.close())
        try:
            await asyncio.sleep(0)
            assert service.closed
            assert not closing.done()
            with pytest.raises(ValueError, match="перезагружа"):
                await service.commit(interaction, pending)
            assert saving.await_count == 1
        finally:
            release.set()
            await asyncio.gather(write, closing)
    assert write.result() is True
    assert await service.store.get(message.id) == pending.record
    assert await service.store.read(message.id) == CARD_BYTES


async def test_close_waits_for_delete_and_rejects_queued_deletion(
    service: QuoteService, interaction: MagicMock, message: MagicMock, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    author = make_interaction(interaction.guild, interaction.user.id)
    entered = asyncio.Event()
    release = asyncio.Event()
    original_remove = service.store.remove

    async def slow_remove(message_id: int) -> bool:
        entered.set()
        await release.wait()
        return await original_remove(message_id)

    with patch.object(service.store, "remove", side_effect=slow_remove) as removing:
        deletion = asyncio.create_task(service.delete(author, message.id))
        await asyncio.wait_for(entered.wait(), timeout=2)
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        queued = asyncio.create_task(service.delete(author, message.id))
        try:
            await asyncio.sleep(0)
            assert service.closed
            assert not closing.done()
            assert not queued.done()
        finally:
            release.set()
            await asyncio.gather(deletion, closing)
            with pytest.raises(ValueError, match="перезагружа"):
                await queued
        removing.assert_awaited_once_with(message.id)
    assert deletion.result() is True
    assert await service.store.get(message.id) is None
    assert not (service.store.root / pending.record.filename).exists()


async def test_removable_rechecks_closed_state_after_index_read(
    service: QuoteService, interaction: MagicMock, message: MagicMock, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    author = make_interaction(interaction.guild, interaction.user.id)
    entered = asyncio.Event()
    release = asyncio.Event()
    original_get = service.store.get

    async def slow_get(message_id: int):
        entered.set()
        await release.wait()
        return await original_get(message_id)

    with patch.object(service.store, "get", side_effect=slow_get):
        checking = asyncio.create_task(service.removable(author, message.id))
        await asyncio.wait_for(entered.wait(), timeout=2)
        try:
            await service.close()
            assert service.closed
        finally:
            release.set()
            with pytest.raises(ValueError, match="перезагружа"):
                await checking
    assert await service.store.get(message.id) == pending.record


async def test_delete_rechecks_server_owner_before_remove(
    service: QuoteService, interaction: MagicMock, message: MagicMock, rendering
) -> None:
    pending = await service.prepare(interaction, message)
    await service.commit(interaction, pending)
    moderator = make_interaction(interaction.guild, message.author.id + 1)
    moderator.permissions = discord.Permissions(manage_messages=True)
    interaction.guild.owner_id = moderator.user.id
    entered = asyncio.Event()
    release = asyncio.Event()
    original_get = service.store.get

    async def slow_get(message_id: int):
        entered.set()
        await release.wait()
        return await original_get(message_id)

    with (
        patch.object(service.store, "get", side_effect=slow_get),
        patch.object(service.store, "remove", wraps=service.store.remove) as removing,
    ):
        deletion = asyncio.create_task(service.delete(moderator, message.id))
        await asyncio.wait_for(entered.wait(), timeout=2)
        interaction.guild.owner_id = 999
        release.set()
        with pytest.raises(ValueError, match="кто её сохранил"):
            await deletion
        removing.assert_not_awaited()
    assert await service.store.get(message.id) == pending.record


async def test_delete_cancel_acknowledges_before_waiting_for_view_lock(
    service: QuoteService, interaction: MagicMock, message: MagicMock
) -> None:
    view = QuoteDeleteConfirmView(service, interaction, message.id)
    await view._lock.acquire()
    cancelling = asyncio.create_task(view.cancel.callback(interaction))
    try:
        await asyncio.sleep(0)
        interaction.response.defer.assert_awaited_once_with()
        assert not cancelling.done()
        interaction.edit_original_response.assert_not_awaited()
    finally:
        view._lock.release()
        await cancelling
    interaction.edit_original_response.assert_awaited_once_with(
        content="Удаление отменено.", view=None
    )
    interaction.response.edit_message.assert_not_awaited()
    assert view.is_finished()
    assert not service.store.root.exists()
