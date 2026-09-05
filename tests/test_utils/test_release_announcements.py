"""Доставка релизов, восстановление после сбоев и отсутствие повторных постов."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from pydantic import ValidationError

from utils.release_announcements import (
    ReleaseAnnouncer,
    ReleaseNote,
    build_announcement_view,
    load_release_note,
)
from utils.ui import testing as ui_testing


@pytest.fixture
def release():
    return ReleaseNote(id="2026.09.05", title="Обновление", text="**Новый профиль**\n@everyone")


@pytest.fixture
def channel():
    result = MagicMock(spec=discord.TextChannel)
    result.id = 10
    result.guild = SimpleNamespace(me=MagicMock(), id=20)
    result.permissions_for.return_value = discord.Permissions(
        view_channel=True, send_messages=True, read_message_history=True
    )
    result.send = AsyncMock(return_value=SimpleNamespace(id=100))

    async def history(**kwargs):
        for message in result.stored_messages:
            yield message

    result.stored_messages = []
    result.history = MagicMock(side_effect=history)
    return result


@pytest.fixture
def announcer(tmp_path):
    return ReleaseAnnouncer(tmp_path / "state.json")


def _message(release, *, author_id=1, message_id=100):
    return SimpleNamespace(
        id=message_id,
        author=SimpleNamespace(id=author_id),
        components=[
            discord.Container(data=component, state=None)
            for component in build_announcement_view(release).to_components()
        ],
    )


def test_load_release_note_preserves_authored_markdown(tmp_path, release):
    path = tmp_path / "release.yaml"
    path.write_text(release.model_dump_json(), encoding="utf-8")
    assert load_release_note(path) == release


@pytest.mark.parametrize(
    "data",
    [{"id": "../bad"}, {"id": "v1", "text": "a" * 3501}, {"id": "v1", "title": ""}],
)
def test_invalid_release_is_rejected(data):
    with pytest.raises(ValidationError):
        ReleaseNote.model_validate(data)


def test_announcement_card_contains_authored_text_and_version(release):
    view = build_announcement_view(release)
    assert release.text in ui_testing.joined_text(view)
    assert release.marker in ui_testing.text_blocks(view)
    assert view.total_children_count <= 40


async def test_empty_release_does_not_touch_delivery_state(announcer, channel):
    assert not await announcer.publish(ReleaseNote(id="v1", text=" \n "), channel, bot_id=1)
    channel.send.assert_not_awaited()
    assert not announcer.state_path.exists()


async def test_first_release_is_saved_and_never_mentions_members(announcer, release, channel):
    assert await announcer.publish(release, channel, bot_id=1)
    assert channel.send.await_args.kwargs["allowed_mentions"].to_dict() == {"parse": []}
    state = json.loads(announcer.state_path.read_text(encoding="utf-8"))
    assert state["releases"][release.id]["message_id"] == 100
    channel.history.assert_not_called()


async def test_restart_or_edit_with_same_id_does_not_repost(announcer, release, channel):
    await announcer.publish(release, channel, bot_id=1)
    restarted = ReleaseAnnouncer(announcer.state_path)
    changed = release.model_copy(update={"text": "Поправленный текст"})
    assert not await restarted.publish(changed, channel, bot_id=1)
    channel.send.assert_awaited_once()


async def test_new_release_is_sent_but_rollback_is_silent(announcer, release, channel):
    await announcer.publish(release, channel, bot_id=1)
    newer = release.model_copy(update={"id": "2026.09.06"})
    assert await announcer.publish(newer, channel, bot_id=1)
    assert not await announcer.publish(release, channel, bot_id=1)
    assert channel.send.await_count == 2


async def test_concurrent_ready_calls_only_send_once(announcer, release, channel):
    result = await asyncio.gather(
        announcer.publish(release, channel, bot_id=1),
        announcer.publish(release, channel, bot_id=1),
    )
    assert sorted(result) == [False, True]
    channel.send.assert_awaited_once()


async def test_failed_send_is_retried_after_history_check(announcer, release, channel):
    channel.send.side_effect = TimeoutError("Сбой сети")
    with pytest.raises(TimeoutError):
        await announcer.publish(release, channel, bot_id=1)
    channel.send.side_effect = None

    assert await announcer.publish(release, channel, bot_id=1)
    channel.history.assert_called_once()
    assert channel.send.await_count == 2


@pytest.mark.parametrize("failure", ["response", "journal"])
async def test_accepted_message_is_recovered_after_lost_ack(announcer, release, channel, failure):
    message = _message(release)

    async def send(**kwargs):
        channel.stored_messages.append(message)
        if failure == "response":
            raise TimeoutError("Discord принял сообщение, но ответ потерялся")
        return message

    channel.send.side_effect = send
    write_state = announcer._write_state
    writes = 0

    def failing_write(state):
        nonlocal writes
        writes += 1
        if failure == "journal" and writes == 2:
            raise OSError("Не удалось сохранить подтверждение")
        write_state(state)

    with patch.object(announcer, "_write_state", side_effect=failing_write):
        with pytest.raises((TimeoutError, OSError)):
            await announcer.publish(release, channel, bot_id=1)

    restarted = ReleaseAnnouncer(announcer.state_path)
    assert not await restarted.publish(release, channel, bot_id=1)
    assert not await restarted.publish(release, channel, bot_id=1)
    channel.send.assert_awaited_once()
    channel.history.assert_called_once()


async def test_other_author_or_release_cannot_suppress_announcement(announcer, release, channel):
    channel.send.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await announcer.publish(release, channel, bot_id=1)
    channel.send.side_effect = None
    channel.stored_messages = [
        _message(release, author_id=2),
        _message(release.model_copy(update={"id": "older"})),
    ]
    assert await announcer.publish(release, channel, bot_id=1)


async def test_unavailable_history_does_not_allow_blind_retry(announcer, release, channel):
    channel.send.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await announcer.publish(release, channel, bot_id=1)
    channel.send.side_effect = None
    channel.history.side_effect = RuntimeError("История недоступна")
    with pytest.raises(RuntimeError, match="История"):
        await announcer.publish(release, channel, bot_id=1)
    channel.send.assert_awaited_once()


async def test_pending_announcement_cannot_move_to_another_channel(announcer, release, channel):
    channel.send.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await announcer.publish(release, channel, bot_id=1)
    channel.id = 999
    with pytest.raises(ValueError, match="другой канал"):
        await announcer.publish(release, channel, bot_id=1)
    channel.send.assert_awaited_once()


async def test_corrupt_journal_is_not_treated_as_first_start(announcer, release, channel):
    announcer.state_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValidationError):
        await announcer.publish(release, channel, bot_id=1)
    channel.send.assert_not_awaited()


async def test_journal_must_be_writable_before_sending(announcer, release, channel):
    with patch.object(announcer, "_write_state", side_effect=OSError("Диск недоступен")):
        with pytest.raises(OSError):
            await announcer.publish(release, channel, bot_id=1)
    channel.send.assert_not_awaited()


async def test_missing_history_permission_prevents_unrecoverable_send(announcer, release, channel):
    channel.permissions_for.return_value.read_message_history = False
    with pytest.raises(PermissionError):
        await announcer.publish(release, channel, bot_id=1)
    channel.send.assert_not_awaited()
    assert not announcer.state_path.exists()
