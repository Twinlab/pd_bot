"""Доставка Wrapped переживает рестарт, частичный сбой и неопределённый ответ Discord."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from config.settings import WrappedScheduleConfig
from utils.wrapped.delivery import (
    HISTORY_LIMIT,
    MAX_ATTEMPTS,
    RETRY_DELAYS,
    DeliveryResult,
    PreparedWrapped,
    WrappedDelivery,
    WrappedPeriod,
    scheduled_periods,
)

NOW = datetime(2026, 10, 5, 9, 2, tzinfo=UTC)
MONTH = WrappedPeriod(kind="monthly", year=2026, month=9)


@pytest.fixture
def channel():
    target = MagicMock(spec=discord.TextChannel)
    target.id = 321
    target.guild.me = MagicMock(spec=discord.Member)
    target.permissions_for.return_value.view_channel = True
    target.permissions_for.return_value.read_message_history = True
    target.send = AsyncMock(return_value=SimpleNamespace(id=987))

    async def empty_history(**kwargs):
        for message in []:
            yield message

    target.history.side_effect = empty_history
    return target


def coordinator(tmp_path):
    return WrappedDelivery(tmp_path / "wrapped_delivery.json", activated_at=NOW)


def payload():
    return AsyncMock(return_value=PreparedWrapped(b"png", "Тот же текст"))


def marker(period=MONTH, recipient_id=0, message_id=987):
    return SimpleNamespace(
        id=message_id,
        author=SimpleNamespace(id=42),
        attachments=[SimpleNamespace(filename=period.filename(recipient_id))],
    )


def with_history(channel, messages):
    async def history(**kwargs):
        for message in messages:
            yield message

    channel.history.side_effect = history


async def deliver(service, channel, *, prepare=None, period=MONTH, recipient_id=0, now=NOW):
    return await service.deliver(
        period,
        bot_id=42,
        recipient_id=recipient_id,
        destination=AsyncMock(return_value=channel),
        prepare=prepare or payload(),
        now=now,
    )


def test_schedule_respects_activation_and_moscow_boundary():
    schedule = WrappedScheduleConfig()
    activation = datetime(2026, 9, 30, 20, tzinfo=UTC)
    slot = datetime(2026, 10, 1, 9, 2, tzinfo=UTC)
    assert scheduled_periods(schedule, activation, slot - timedelta(seconds=1)) == []
    assert scheduled_periods(schedule, activation, slot) == [MONTH]
    assert scheduled_periods(schedule, slot, slot + timedelta(days=1)) == []


def test_yearly_and_personal_use_configured_day_and_existing_current_year():
    schedule = WrappedScheduleConfig(
        hour=0, minute=15, yearly_month=10, yearly_day=2, personal_month=10, personal_day=2
    )
    activation = datetime(2026, 10, 1, 20, tzinfo=UTC)
    periods = scheduled_periods(schedule, activation, datetime(2026, 10, 1, 21, 15, tzinfo=UTC))
    assert {p.kind for p in periods} == {"yearly", "personal"}
    assert {p.year for p in periods} == {2026}


async def test_first_start_skips_passed_slot_but_restart_catches_later_slot(tmp_path):
    service = coordinator(tmp_path)
    assert await service.due_periods(WrappedScheduleConfig(), now=NOW) == []
    restarted = WrappedDelivery(service.state_path, activated_at=NOW + timedelta(days=100))
    due = await restarted.due_periods(
        WrappedScheduleConfig(), now=datetime(2026, 11, 2, 8, tzinfo=UTC)
    )
    assert due == [WrappedPeriod(kind="monthly", year=2026, month=10)]
    assert json.loads(service.state_path.read_text())["activated_at"].startswith("2026-10-05")


async def test_catchup_is_bounded_to_one_period_per_kind(tmp_path):
    service = coordinator(tmp_path)
    due = await service.due_periods(WrappedScheduleConfig(), now=datetime(2027, 3, 2, tzinfo=UTC))
    assert len(due) == 3
    assert next(p for p in due if p.kind == "monthly").month == 10


async def test_pending_is_durable_before_send_and_restart_does_not_repeat(tmp_path, channel):
    service = coordinator(tmp_path)
    prepared = payload()

    async def send(**kwargs):
        record = json.loads(service.state_path.read_text())["deliveries"][MONTH.delivery_key()]
        assert record["status"] == "pending"
        assert record["destination_id"] == channel.id
        assert kwargs["file"].filename == MONTH.filename()
        assert kwargs["content"] == "Тот же текст"
        return SimpleNamespace(id=987)

    channel.send.side_effect = send
    assert await deliver(service, channel, prepare=prepared) == DeliveryResult.SENT
    assert (
        await deliver(coordinator(tmp_path), channel, prepare=prepared)
        == DeliveryResult.ALREADY_SENT
    )
    channel.send.assert_awaited_once()
    prepared.assert_awaited_once()


async def test_uncertain_send_reconciles_history_before_retry(tmp_path, channel):
    service = coordinator(tmp_path)
    prepared = payload()
    channel.send.side_effect = TimeoutError()
    assert await deliver(service, channel, prepare=prepared) == DeliveryResult.DEFERRED
    with_history(channel, [marker()])
    result = await deliver(
        coordinator(tmp_path), channel, prepare=prepared, now=NOW + timedelta(minutes=5)
    )
    assert result == DeliveryResult.ALREADY_SENT
    channel.send.assert_awaited_once()
    prepared.assert_awaited_once()
    assert channel.history.call_args.kwargs["limit"] == HISTORY_LIMIT + 1


async def test_receipt_write_crash_recovers_without_second_message(tmp_path, channel):
    service = coordinator(tmp_path)
    original_write = service._write

    def fail_receipt(journal):
        if any(record.status == "sent" for record in journal.deliveries.values()):
            raise OSError("disk full")
        original_write(journal)

    with patch.object(service, "_write", side_effect=fail_receipt):
        with pytest.raises(OSError):
            await deliver(service, channel)
    with_history(channel, [marker()])
    assert (
        await deliver(coordinator(tmp_path), channel, now=NOW + timedelta(minutes=5))
        == DeliveryResult.ALREADY_SENT
    )
    channel.send.assert_awaited_once()


async def test_complete_empty_history_allows_bounded_retry(tmp_path, channel):
    service = coordinator(tmp_path)
    channel.send.side_effect = [TimeoutError(), SimpleNamespace(id=987)]
    assert await deliver(service, channel) == DeliveryResult.DEFERRED
    assert (
        await deliver(service, channel, now=NOW + timedelta(minutes=4)) == DeliveryResult.DEFERRED
    )
    channel.history.assert_not_called()
    assert await deliver(service, channel, now=NOW + timedelta(minutes=5)) == DeliveryResult.SENT
    assert channel.send.await_count == 2
    channel.history.assert_called_once()


@pytest.mark.parametrize("failure", ["denied", "http", "incomplete", "destination_changed"])
async def test_unverified_history_fails_closed(tmp_path, channel, failure):
    service = coordinator(tmp_path)
    channel.send.side_effect = TimeoutError()
    await deliver(service, channel)
    if failure == "denied":
        channel.permissions_for.return_value.read_message_history = False
    elif failure == "http":
        channel.history.side_effect = discord.Forbidden(MagicMock(status=403), "denied")
    elif failure == "incomplete":
        with_history(
            channel,
            [SimpleNamespace(author=SimpleNamespace(id=99), attachments=[])] * (HISTORY_LIMIT + 1),
        )
    else:
        channel.id = 999
    assert (
        await deliver(service, channel, now=NOW + timedelta(minutes=5))
        == DeliveryResult.MANUAL_REVIEW
    )
    assert (
        await deliver(service, channel, now=NOW + timedelta(days=2)) == DeliveryResult.MANUAL_REVIEW
    )
    channel.send.assert_awaited_once()


async def test_manual_old_period_retry_is_not_lost_by_activation_boundary(tmp_path, channel):
    service = coordinator(tmp_path)
    old = WrappedPeriod(kind="yearly", year=2024)
    await deliver(service, channel, period=old, prepare=AsyncMock(side_effect=RuntimeError("db")))
    assert await service.due_periods(WrappedScheduleConfig(), now=NOW + timedelta(minutes=5)) == [
        old
    ]


async def test_retry_budget_is_durable_across_restarts(tmp_path, channel):
    prepared = AsyncMock(side_effect=RuntimeError("db"))
    current = NOW
    for attempt in range(MAX_ATTEMPTS):
        result = await deliver(coordinator(tmp_path), channel, prepare=prepared, now=current)
        current += timedelta(seconds=RETRY_DELAYS[attempt])
    assert result == DeliveryResult.MANUAL_REVIEW
    assert (
        await deliver(coordinator(tmp_path), channel, prepare=prepared, now=current)
        == DeliveryResult.MANUAL_REVIEW
    )
    assert prepared.await_count == MAX_ATTEMPTS
    channel.send.assert_not_awaited()


async def test_personal_snapshot_and_partial_delivery_survive_restart(tmp_path, channel):
    service = coordinator(tmp_path)
    discover = AsyncMock(return_value=[1, 2, 3])
    assert await service.personal_recipients(2026, discover, now=NOW) == [1, 2, 3]
    period = WrappedPeriod(kind="personal", year=2026)
    assert await deliver(service, channel, period=period, recipient_id=1) == DeliveryResult.SENT
    channel.send.side_effect = discord.Forbidden(MagicMock(status=403), "DM closed")
    assert (
        await deliver(service, channel, period=period, recipient_id=2)
        == DeliveryResult.PERMANENT_FORBIDDEN
    )
    channel.send.side_effect = [TimeoutError(), SimpleNamespace(id=988)]
    assert await deliver(service, channel, period=period, recipient_id=3) == DeliveryResult.DEFERRED
    restarted = coordinator(tmp_path)
    discover.return_value = [4]
    assert await restarted.personal_recipients(2026, discover, now=NOW) == [1, 2, 3]
    assert (
        await deliver(restarted, channel, period=period, recipient_id=1)
        == DeliveryResult.ALREADY_SENT
    )
    assert (
        await deliver(restarted, channel, period=period, recipient_id=2)
        == DeliveryResult.PERMANENT_FORBIDDEN
    )
    assert (
        await deliver(
            restarted, channel, period=period, recipient_id=3, now=NOW + timedelta(minutes=5)
        )
        == DeliveryResult.SENT
    )
    assert channel.send.await_count == 4
    discover.assert_awaited_once()


async def test_cancelled_fifth_recipient_discovery_stays_within_budget(tmp_path):
    service = coordinator(tmp_path)
    current = NOW
    for attempt in range(MAX_ATTEMPTS - 1):
        assert (
            await service.personal_recipients(
                2026, AsyncMock(side_effect=RuntimeError("db")), now=current
            )
            is None
        )
        current += timedelta(seconds=RETRY_DELAYS[attempt])
    started = asyncio.Event()

    async def hang():
        started.set()
        await asyncio.Event().wait()

    job = asyncio.create_task(service.personal_recipients(2026, hang, now=current))
    await started.wait()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    discover = AsyncMock(return_value=[1])
    assert (
        await coordinator(tmp_path).personal_recipients(
            2026, discover, now=current + timedelta(days=2)
        )
        is None
    )
    discover.assert_not_awaited()
    batch = json.loads(service.state_path.read_text())["personal_batches"]["2026"]
    assert batch["attempts"] == MAX_ATTEMPTS
    assert batch["blocked"] is True


@pytest.mark.parametrize(
    "corruption",
    [
        "invalid_json",
        "missing_fields",
        "missing_version",
        "missing_deliveries",
        "duplicate_key",
        "missing_record_status",
    ],
)
async def test_malformed_journal_never_sends(tmp_path, channel, corruption):
    service = coordinator(tmp_path)
    await service.due_periods(WrappedScheduleConfig(), now=NOW)
    if corruption == "invalid_json":
        raw = "{"
    elif corruption == "missing_fields":
        raw = "{}"
    elif corruption in {"missing_version", "missing_deliveries"}:
        journal = json.loads(service.state_path.read_text())
        del journal[corruption.removeprefix("missing_")]
        raw = json.dumps(journal)
    elif corruption == "duplicate_key":
        raw = service.state_path.read_text().replace('"version": 1', '"version": 1, "version": 1')
    else:
        await deliver(service, channel)
        journal = json.loads(service.state_path.read_text())
        del journal["deliveries"][MONTH.delivery_key()]["status"]
        raw = json.dumps(journal)
        channel.send.reset_mock()
    service.state_path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        await deliver(coordinator(tmp_path), channel)
    channel.send.assert_not_awaited()


async def test_parallel_manual_and_automatic_attempts_send_once(tmp_path, channel):
    service = coordinator(tmp_path)
    results = await asyncio.gather(deliver(service, channel), deliver(service, channel))
    assert results == [DeliveryResult.SENT, DeliveryResult.ALREADY_SENT]
    channel.send.assert_awaited_once()


async def test_queued_attempt_uses_time_after_lock_and_preserves_retry_delay(tmp_path, channel):
    service = coordinator(tmp_path)
    channel.send.side_effect = TimeoutError()
    later = NOW + timedelta(hours=1)
    await service._lock.acquire()
    with patch("utils.wrapped.delivery.datetime", wraps=datetime) as clock:
        clock.now.return_value = NOW
        job = asyncio.create_task(deliver(service, channel, now=None))
        await asyncio.sleep(0)
        clock.now.return_value = later
        service._lock.release()
        assert await job == DeliveryResult.DEFERRED
        assert await deliver(service, channel, now=None) == DeliveryResult.DEFERRED
    record = json.loads(service.state_path.read_text())["deliveries"][MONTH.delivery_key()]
    assert datetime.fromisoformat(record["started_at"]) == later
    assert datetime.fromisoformat(record["next_retry"]) == later + timedelta(minutes=5)
    channel.history.assert_not_called()
    channel.send.assert_awaited_once()


async def test_cancelled_send_remains_pending_and_reconciles_after_restart(tmp_path, channel):
    service = coordinator(tmp_path)
    entered_send = asyncio.Event()

    async def send(**kwargs):
        entered_send.set()
        await asyncio.Event().wait()

    channel.send.side_effect = send
    job = asyncio.create_task(deliver(service, channel))
    await entered_send.wait()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    record = json.loads(service.state_path.read_text())["deliveries"][MONTH.delivery_key()]
    assert record["status"] == "pending"
    with_history(channel, [marker()])
    assert (
        await deliver(coordinator(tmp_path), channel, now=NOW + timedelta(minutes=5))
        == DeliveryResult.ALREADY_SENT
    )
    channel.send.assert_awaited_once()
