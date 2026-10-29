"""Доставка переживает перезапуск и не повторяет подтверждённые части."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time

from utils.scheduled_delivery import ScheduledDelivery


class Channel:
    id = 42

    def __init__(self):
        self.messages = []

    async def history(self, **kwargs):
        for message in self.messages[: kwargs["limit"]]:
            yield message


def message(message_id, text, author=99):
    return SimpleNamespace(id=message_id, content=text, author=SimpleNamespace(id=author))


def matches(part, msg):
    return part["content"] == msg.content


async def test_completed_delivery_does_not_rebuild_or_resend_after_restart(tmp_path):
    path = tmp_path / "state.json"
    channel = Channel()
    prepare = AsyncMock(return_value=[{"content": "snapshot"}])
    send = AsyncMock(return_value=message(1, "snapshot"))
    for _ in range(2):
        result = await ScheduledDelivery(path).deliver(
            "day", channel=channel, bot_id=99, prepare=prepare, send=send, matches=matches
        )
        assert result == [{"content": "snapshot"}]
    prepare.assert_awaited_once()
    send.assert_awaited_once()


async def test_lost_ack_is_reconciled_before_remaining_parts(tmp_path):
    path = tmp_path / "state.json"
    channel = Channel()
    prepare = AsyncMock(return_value=[{"content": "one"}, {"content": "two"}])

    async def lost_ack(part):
        channel.messages.append(message(1, part["content"]))
        raise TimeoutError()

    with freeze_time("2026-10-29 12:00:00") as clock:
        with pytest.raises(TimeoutError):
            await ScheduledDelivery(path).deliver(
                "month", channel=channel, bot_id=99, prepare=prepare, send=lost_ack, matches=matches
            )
        clock.tick(180)
        send = AsyncMock(return_value=message(2, "two"))
        result = await ScheduledDelivery(path).deliver(
            "month", channel=channel, bot_id=99, prepare=prepare, send=send, matches=matches
        )
    assert len(result) == 2
    send.assert_awaited_once_with({"content": "two"})
    prepare.assert_awaited_once()


async def test_definitely_absent_message_retries_saved_snapshot(tmp_path):
    path = tmp_path / "state.json"
    channel = Channel()
    prepare = AsyncMock(return_value=[{"content": "original"}])
    with freeze_time("2026-10-29 12:00:00") as clock:
        with pytest.raises(TimeoutError):
            await ScheduledDelivery(path).deliver(
                "day",
                channel=channel,
                bot_id=99,
                prepare=prepare,
                send=AsyncMock(side_effect=TimeoutError),
                matches=matches,
            )
        clock.tick(180)
        prepare.side_effect = AssertionError("Must not query archived data again")
        send = AsyncMock(return_value=message(2, "original"))
        await ScheduledDelivery(path).deliver(
            "day", channel=channel, bot_id=99, prepare=prepare, send=send, matches=matches
        )
    send.assert_awaited_once_with({"content": "original"})


async def test_incomplete_history_does_not_authorize_duplicate_send(tmp_path):
    path = tmp_path / "state.json"
    channel = Channel()
    prepare = AsyncMock(return_value=[{"content": "target"}])
    with freeze_time("2026-10-29 12:00:00") as clock:
        with pytest.raises(TimeoutError):
            await ScheduledDelivery(path).deliver(
                "day",
                channel=channel,
                bot_id=99,
                prepare=prepare,
                send=AsyncMock(side_effect=TimeoutError),
                matches=matches,
            )
        clock.tick(180)
        channel.messages = [message(i + 1, "unrelated") for i in range(101)]
        send = AsyncMock()
        assert (
            await ScheduledDelivery(path).deliver(
                "day", channel=channel, bot_id=99, prepare=prepare, send=send, matches=matches
            )
            is None
        )
        send.assert_not_awaited()


async def test_corrupt_journal_is_not_replaced(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version":999}', encoding="utf-8")
    prepare, send = AsyncMock(), AsyncMock()
    with pytest.raises(ValueError):
        await ScheduledDelivery(path).deliver(
            "day", channel=Channel(), bot_id=99, prepare=prepare, send=send, matches=matches
        )
    assert path.read_text() == '{"version":999}'
    prepare.assert_not_awaited()
    send.assert_not_awaited()


async def test_pending_keys_and_grace_period_survive_restart(tmp_path):
    path = tmp_path / "state.json"
    channel = Channel()
    prepare = AsyncMock(return_value=[{"content": "target"}])
    with freeze_time("2026-10-29 12:00:00"):
        with pytest.raises(TimeoutError):
            await ScheduledDelivery(path).deliver(
                "daily:2026-10-28",
                channel=channel,
                bot_id=99,
                prepare=prepare,
                send=AsyncMock(side_effect=TimeoutError),
                matches=matches,
            )
        delivery = ScheduledDelivery(path)
        assert await delivery.pending_keys("daily:") == ["daily:2026-10-28"]
        assert await delivery.pending_keys("monthly:") == []
        send = AsyncMock()
        assert (
            await delivery.deliver(
                "daily:2026-10-28",
                channel=channel,
                bot_id=99,
                prepare=prepare,
                send=send,
                matches=matches,
            )
            is None
        )
        send.assert_not_awaited()


async def test_failed_save_after_send_reloads_disk_before_retry(tmp_path, monkeypatch):
    delivery = ScheduledDelivery(tmp_path / "state.json")
    channel = Channel()
    prepare = AsyncMock(return_value=[{"content": "target"}])
    original_write = delivery._write
    fail_next = False

    def write(journal):
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise OSError("disk full")
        original_write(journal)

    monkeypatch.setattr(delivery, "_write", write)

    async def send_once(part):
        nonlocal fail_next
        sent = message(1, part["content"])
        channel.messages.append(sent)
        fail_next = True
        return sent

    with freeze_time("2026-10-29 12:00:00") as clock:
        with pytest.raises(OSError):
            await delivery.deliver(
                "day", channel=channel, bot_id=99, prepare=prepare, send=send_once, matches=matches
            )
        clock.tick(180)
        send = AsyncMock()
        assert await delivery.deliver(
            "day", channel=channel, bot_id=99, prepare=prepare, send=send, matches=matches
        ) == [{"content": "target"}]
        send.assert_not_awaited()
        assert await delivery.pending_keys("") == []


async def test_other_author_cannot_confirm_delivery(tmp_path):
    path = tmp_path / "state.json"
    channel = Channel()
    prepare = AsyncMock(return_value=[{"content": "target"}])
    with freeze_time("2026-10-29 12:00:00") as clock:
        with pytest.raises(TimeoutError):
            await ScheduledDelivery(path).deliver(
                "day",
                channel=channel,
                bot_id=99,
                prepare=prepare,
                send=AsyncMock(side_effect=TimeoutError),
                matches=matches,
            )
        clock.tick(180)
        channel.messages = [message(1, "target", author=100)]
        send = AsyncMock(return_value=message(2, "target"))
        await ScheduledDelivery(path).deliver(
            "day", channel=channel, bot_id=99, prepare=prepare, send=send, matches=matches
        )
    send.assert_awaited_once()
