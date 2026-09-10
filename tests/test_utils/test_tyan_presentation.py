"""Проверки CV2-карточки /tyan и её отправки через общий обработчик."""

from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import discord
import pytest

from utils.error_handler import safe_send
from utils.tyan.presentation import build_tyan_card
from utils.tyan.types import Roll


def result():
    return Roll(user_id=123, day=date(2026, 9, 11),
                created_at=datetime(2026, 9, 10, 21, tzinfo=UTC),
                kind="normal", text="грац, тебе досталась 24-летняя 170/60 бимба")


@pytest.mark.parametrize("day,next_date", [
    (date(2026, 9, 11), "12.09.2026"),
    (date(2026, 12, 31), "01.01.2027"),
])
@pytest.mark.parametrize("kind,color", [("normal", 0x5865F2), ("mother", 0xF0B232), ("none", 0x747F8D)])
def test_card_has_owner_mention_saved_text_and_next_moscow_date(day, next_date, kind, color):
    row = replace(result(), day=day, kind=kind)
    view = build_tyan_card(row)
    assert isinstance(view, discord.ui.LayoutView)
    assert view.has_components_v2()
    assert view.timeout is None
    card = view.to_components()[0]
    assert card["accent_color"] == color
    assert card["components"][0]["content"] == "## Тянка <@123> на сегодня"
    assert card["components"][1]["content"] == row.text
    assert card["components"][2]["type"] == 14
    assert f"{next_date} в 00:00 МСК" in card["components"][3]["content"]


@pytest.mark.parametrize("mode", ["context", "response", "followup"])
async def test_safe_send_passes_cv2_without_forbidden_embed_or_content(
    mock_context, mock_interaction, mode,
):
    target = mock_context if mode == "context" else mock_interaction
    mock_interaction.response.is_done.return_value = mode == "followup"
    mock_interaction.original_response = AsyncMock()
    view = build_tyan_card(result())
    mentions = discord.AllowedMentions.none()
    await safe_send(target, view=view, allowed_mentions=mentions)
    send = (mock_context.send if mode == "context"
            else mock_interaction.followup.send if mode == "followup"
            else mock_interaction.response.send_message)
    send.assert_awaited_once()
    payload = send.await_args.kwargs
    assert payload["view"] is view
    assert payload["allowed_mentions"].to_dict() == {"parse": []}
    assert "content" not in payload and "embed" not in payload


async def test_safe_send_rejects_mixed_cv2_and_legacy_content(mock_context):
    assert await safe_send(mock_context, "лишний текст", view=build_tyan_card(result())) is None
    mock_context.send.assert_not_awaited()

