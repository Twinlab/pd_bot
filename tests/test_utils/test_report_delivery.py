"""Повторы автоматических отчётов с настоящим журналом во временной папке."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
from freezegun import freeze_time

from utils.activity.reports import (
    run_automatic_daily_report,
    run_automatic_monthly_report,
    send_daily_report,
)
from utils.scheduled_delivery import ScheduledDelivery


def report_cog(path):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 42
    channel.send = AsyncMock(return_value=SimpleNamespace(id=123))

    async def history(**kwargs):
        for message in []:
            yield message

    channel.history = history
    bot = MagicMock()
    bot.user.id = 99
    bot.get_channel.return_value = channel
    manager = AsyncMock()
    manager.get_daily_stats.return_value = {}
    manager.get_aggregated_monthly_stats.return_value = {}
    manager.get_pending_daily_dates.return_value = []
    manager.transfer_daily_to_monthly.return_value = True
    return SimpleNamespace(
        bot=bot,
        data_manager=manager,
        report_delivery=ScheduledDelivery(path),
        update_current_activities=AsyncMock(),
    ), channel


async def test_archive_failure_does_not_repeat_already_sent_day(tmp_path):
    path = tmp_path / "reports.json"
    cog, channel = report_cog(path)
    with freeze_time("2026-10-29 15:00:00") as clock:
        await cog.report_delivery.activation_time()
        clock.move_to("2026-10-30 00:00:00")
        cog.data_manager.transfer_daily_to_monthly.return_value = False
        await run_automatic_daily_report(cog)
        cog.report_delivery = ScheduledDelivery(path)
        cog.data_manager.transfer_daily_to_monthly.return_value = True
        await run_automatic_daily_report(cog)
    channel.send.assert_awaited_once()
    cog.data_manager.get_daily_stats.assert_awaited_once_with(date(2026, 10, 29), strict=True)
    assert cog.data_manager.transfer_daily_to_monthly.await_count == 2


async def test_failed_empty_day_survives_next_midnight(tmp_path):
    cog, channel = report_cog(tmp_path / "reports.json")
    with freeze_time("2026-10-29 15:00:00") as clock:
        await cog.report_delivery.activation_time()
        clock.move_to("2026-10-30 00:00:00")
        channel.send.side_effect = TimeoutError
        await run_automatic_daily_report(cog)
        cog.data_manager.transfer_daily_to_monthly.assert_not_awaited()
        clock.move_to("2026-10-31 00:00:00")
        channel.send.side_effect = None
        await run_automatic_daily_report(cog)
    dates = [call.args[0] for call in cog.data_manager.get_daily_stats.await_args_list]
    assert dates == [date(2026, 10, 29), date(2026, 10, 30)]
    assert "29.10.2026" in channel.send.await_args_list[-2].args[0]
    assert "30.10.2026" in channel.send.await_args_list[-1].args[0]
    assert await cog.report_delivery.pending_keys("daily:") == []


async def test_database_error_is_not_frozen_as_empty_report(tmp_path):
    cog, channel = report_cog(tmp_path / "reports.json")
    cog.data_manager.get_daily_stats.side_effect = RuntimeError("db unavailable")
    assert not await send_daily_report(
        date(2026, 10, 29), cog.bot, cog.data_manager, delivery=cog.report_delivery
    )
    channel.send.assert_not_awaited()
    cog.data_manager.get_daily_stats.side_effect = None
    assert await send_daily_report(
        date(2026, 10, 29), cog.bot, cog.data_manager, delivery=cog.report_delivery
    )
    channel.send.assert_awaited_once()


async def test_monthly_catches_missed_first_day_once(tmp_path):
    cog, channel = report_cog(tmp_path / "reports.json")
    with freeze_time("2026-10-29 15:00:00") as clock:
        await cog.report_delivery.activation_time()
        clock.move_to("2026-11-01 08:59:00")
        await run_automatic_monthly_report(cog)
        channel.send.assert_not_awaited()
        clock.move_to("2026-11-02 12:00:00")
        await run_automatic_monthly_report(cog)
        await run_automatic_monthly_report(cog)
    channel.send.assert_awaited_once()
    cog.data_manager.get_aggregated_monthly_stats.assert_awaited_once_with(
        2026, 10, strict=True, include_pending=True
    )


async def test_pending_month_is_retried_even_after_next_month(tmp_path):
    cog, channel = report_cog(tmp_path / "reports.json")
    with freeze_time("2026-10-29 15:00:00") as clock:
        await cog.report_delivery.activation_time()
        clock.move_to("2026-11-01 12:00:00")
        channel.send.side_effect = TimeoutError
        await run_automatic_monthly_report(cog)
        clock.move_to("2026-12-02 12:00:00")
        channel.send.side_effect = None
        await run_automatic_monthly_report(cog)
    assert [
        call.args for call in cog.data_manager.get_aggregated_monthly_stats.await_args_list
    ] == [
        (2026, 10),
        (2026, 11),
    ]
    assert "Октябрь 2026" in channel.send.await_args_list[-2].args[0]
    assert "Ноябрь 2026" in channel.send.await_args_list[-1].args[0]


async def test_first_activation_does_not_publish_old_archive(tmp_path):
    cog, channel = report_cog(tmp_path / "reports.json")
    with freeze_time("2026-11-02 12:00:00"):
        cog.data_manager.get_pending_daily_dates.return_value = [date(2026, 10, 15)]
        await run_automatic_daily_report(cog)
        await run_automatic_monthly_report(cog)
    channel.send.assert_not_awaited()
    assert cog.data_manager.transfer_daily_to_monthly.await_count == 2
