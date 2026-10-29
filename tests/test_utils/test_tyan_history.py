"""История показывает сохранённые выдачи только их владельцу."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils.tyan.history import TyanHistoryButton, TyanHistoryView
from utils.tyan.types import Roll
from utils.tyan_data_manager import TyanDataManager


def roll(day, kind="normal"):
    return Roll(
        123, date(2026, 10, day), datetime(2026, 10, day, tzinfo=UTC), kind, f"Снимок {day}"
    )


def interaction(user_id=123):
    result = MagicMock(spec=discord.Interaction)
    result.user.id = user_id
    result.response.defer = AsyncMock()
    result.response.send_message = AsyncMock()
    result.edit_original_response = AsyncMock()
    return result


async def test_cursor_navigation_preserves_dates_and_snapshot_text():
    manager = MagicMock(spec=TyanDataManager)
    manager.get_history = AsyncMock(
        side_effect=[[roll(28, "mother"), roll(27)], [roll(29), roll(28)]]
    )
    view = TyanHistoryView(manager, 123, [roll(29), roll(28)])
    await view.change_page(interaction(), older=True)
    manager.get_history.assert_awaited_with(123, before=date(2026, 10, 29))
    card = view.to_components()[0]
    assert card["components"][1]["content"] == "Снимок 28"
    assert card["accent_color"] == 0xF0B232
    await view.change_page(interaction(), older=False)
    manager.get_history.assert_awaited_with(123, before=None)
    assert view.rolls[0].day == date(2026, 10, 29)


async def test_other_user_cannot_read_next_page():
    manager = MagicMock(spec=TyanDataManager)
    view = TyanHistoryView(manager, 123, [roll(29), roll(28)])
    with patch("utils.tyan.history.safe_send_error", new=AsyncMock()) as error:
        await view.change_page(interaction(456), older=True)
    error.assert_awaited_once()
    manager.get_history.assert_not_called()


async def test_failed_read_does_not_advance_cursor():
    manager = MagicMock(spec=TyanDataManager)
    manager.get_history = AsyncMock(side_effect=RuntimeError("database unavailable"))
    view = TyanHistoryView(manager, 123, [roll(29), roll(28)])
    with pytest.raises(RuntimeError):
        await view.change_page(interaction(), older=True)
    assert view.cursors == [None]
    assert view.rolls[0].day.day == 29


async def test_timeout_disables_navigation():
    view = TyanHistoryView(MagicMock(), 123, [roll(29), roll(28)])
    view.message = MagicMock(spec=discord.Message)
    view.message.edit = AsyncMock()
    await view.on_timeout()
    assert all(
        item.disabled for item in view.walk_children() if isinstance(item, discord.ui.Button)
    )
    view.message.edit.assert_awaited_once()


async def test_history_button_uses_clicker_and_ephemeral_response():
    event = interaction(456)
    manager = MagicMock(spec=TyanDataManager)
    manager.get_history = AsyncMock(return_value=[])
    with (
        patch("utils.tyan.history.TyanDataManager", return_value=manager),
        patch("utils.tyan.history.safe_send", new=AsyncMock()) as send,
    ):
        await TyanHistoryButton().callback(event)
    manager.get_history.assert_awaited_once_with(456)
    event.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    assert send.await_args.kwargs["ephemeral"] is True
    assert "пустая" in send.await_args.kwargs["view"].to_components()[0]["content"]


async def test_dynamic_button_reconstruction_and_dm_rejection():
    button = await TyanHistoryButton.from_custom_id(interaction(), MagicMock(), MagicMock())
    assert button.item.custom_id == "tyan:history"
    event = interaction()
    event.guild = None
    with patch("utils.tyan.history.safe_send_error", new=AsyncMock()) as error:
        await button.callback(event)
    error.assert_awaited_once()
