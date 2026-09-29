"""Тесты пограничной логики голосовой статистики."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.user_stats import UserStatsTracker


@pytest.mark.asyncio
async def test_queued_voice_interval_splits_moscow_midnight() -> None:
    """Голосовые секунды по обе стороны полуночи записываются в разные даты."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker.stats_manager = MagicMock()
    tracker.stats_manager.add_voice_seconds = AsyncMock()

    tracker._pending_voice = {}
    tracker._queue_voice_interval(
        123,
        datetime(2026, 7, 23, 20, 59, 58, tzinfo=UTC),
        datetime(2026, 7, 23, 21, 0, 3, tzinfo=UTC),
    )

    assert await tracker._flush_pending_voice()
    assert tracker.stats_manager.add_voice_seconds.await_args_list == [
        ((123, 2), {"target_date": date(2026, 7, 23)}),
        ((123, 3), {"target_date": date(2026, 7, 24)}),
    ]


@pytest.mark.asyncio
async def test_flush_active_serializes_concurrent_jobs() -> None:
    """Полуночный и периодический flush не учитывают один голосовой интервал дважды."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker._voice_lock = asyncio.Lock()
    tracker.bot = MagicMock()
    tracker.bot.guilds = []
    tracker.stats_manager = MagicMock()
    write_started = asyncio.Event()
    allow_write = asyncio.Event()

    async def slow_write(*args, **kwargs) -> None:
        write_started.set()
        await allow_write.wait()

    tracker.stats_manager.add_voice_seconds = AsyncMock(side_effect=slow_write)
    first_now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    tracker.voice_sessions = {123: first_now - timedelta(minutes=2)}
    tracker._pending_voice = {}

    with patch("cogs.user_stats.datetime") as mock_datetime:
        mock_datetime.now.return_value = first_now
        first_flush = asyncio.create_task(tracker._flush_active(restart=True))
        await write_started.wait()
        second_flush = asyncio.create_task(tracker._flush_active(restart=True))
        await asyncio.sleep(0)
        allow_write.set()
        await asyncio.gather(first_flush, second_flush)

    tracker.stats_manager.add_voice_seconds.assert_awaited_once()
    assert tracker.voice_sessions == {}


@pytest.mark.asyncio
async def test_daily_transfer_processes_stale_dates() -> None:
    """После простоя переносит в месяцы все старые дневные user-stats."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker._voice_lock = asyncio.Lock()
    tracker.voice_sessions = {}
    tracker._pending_voice = {}
    tracker.stats_manager = MagicMock()
    tracker.stats_manager.get_pending_daily_dates = AsyncMock(
        return_value=[date(2026, 8, 17), date(2026, 8, 18)]
    )
    tracker.stats_manager.transfer_daily_to_monthly = AsyncMock(return_value=True)

    with patch("cogs.user_stats.moscow_today", return_value=date(2026, 8, 20)):
        await UserStatsTracker.daily_transfer.coro(tracker)

    tracker.stats_manager.get_pending_daily_dates.assert_awaited_once_with(date(2026, 8, 20))
    transferred_dates = [
        call.args[0]
        for call in tracker.stats_manager.transfer_daily_to_monthly.await_args_list
    ]
    assert transferred_dates == [date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)]


@pytest.mark.asyncio
async def test_closed_voice_session_retries_fixed_duration_after_db_failure() -> None:
    """Сбой БД при выходе не начисляет время до следующего успешного сохранения."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker._pending_voice = {}
    tracker._voice_lock = asyncio.Lock()
    started = datetime(2026, 9, 20, 12, tzinfo=UTC)
    tracker.voice_sessions = {123: started}
    tracker.stats_manager = MagicMock()
    tracker.stats_manager.add_voice_seconds = AsyncMock(side_effect=[RuntimeError("DB"), None])

    await tracker._close_session(123, started + timedelta(minutes=2))
    assert tracker.voice_sessions == {}
    assert tracker._pending_voice == {(123, date(2026, 9, 20)): 120}

    with patch("cogs.user_stats.datetime") as mock_datetime:
        mock_datetime.now.return_value = started + timedelta(minutes=7)
        assert await tracker._flush_active(restart=True)

    assert [call.args[1] for call in tracker.stats_manager.add_voice_seconds.await_args_list] == [
        120,
        120,
    ]
    assert tracker._pending_voice == {}


@pytest.mark.asyncio
async def test_midnight_retry_does_not_repeat_successful_day() -> None:
    """После частичной записи повторяется только неуспешная часть интервала."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker._pending_voice = {}
    tracker._voice_lock = asyncio.Lock()
    tracker.voice_sessions = {123: datetime(2026, 9, 20, 20, 59, 30, tzinfo=UTC)}
    tracker.stats_manager = MagicMock()
    tracker.stats_manager.add_voice_seconds = AsyncMock(
        side_effect=[None, RuntimeError("DB"), None]
    )

    await tracker._close_session(123, datetime(2026, 9, 20, 21, 0, 30, tzinfo=UTC))
    assert tracker.voice_sessions == {}
    assert tracker._pending_voice == {(123, date(2026, 9, 21)): 30}
    assert await tracker._flush_active(restart=True)

    assert tracker.stats_manager.add_voice_seconds.await_args_list == [
        ((123, 30), {"target_date": date(2026, 9, 20)}),
        ((123, 30), {"target_date": date(2026, 9, 21)}),
        ((123, 30), {"target_date": date(2026, 9, 21)}),
    ]
    assert tracker._pending_voice == {}


@pytest.mark.asyncio
async def test_active_voice_retry_preserves_elapsed_time_once() -> None:
    """Неуспешный flush не повторяет уже поставленный в очередь отрезок."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker._pending_voice = {}
    tracker._voice_lock = asyncio.Lock()
    tracker.bot = MagicMock()
    tracker.bot.guilds = [MagicMock()]
    started = datetime(2026, 9, 20, 12, tzinfo=UTC)
    tracker.voice_sessions = {123: started}
    tracker.stats_manager = MagicMock()
    tracker.stats_manager.add_voice_seconds = AsyncMock(side_effect=[RuntimeError("DB"), None])

    with (
        patch("cogs.user_stats.datetime") as mock_datetime,
        patch("cogs.user_stats.member_is_active", return_value=True),
    ):
        mock_datetime.now.return_value = started + timedelta(minutes=2)
        assert not await tracker._flush_active(restart=True)
        assert tracker.voice_sessions[123] == started + timedelta(minutes=2)
        mock_datetime.now.return_value = started + timedelta(minutes=5)
        assert await tracker._flush_active(restart=True)

    assert tracker.stats_manager.add_voice_seconds.await_args.args == (123, 300)
    assert tracker._pending_voice == {}


@pytest.mark.asyncio
async def test_daily_transfer_waits_for_pending_voice() -> None:
    """Дневные итоги не архивируются до успешного сохранения голосовой очереди."""
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    tracker._pending_voice = {(123, date(2026, 9, 19)): 120}
    tracker._voice_lock = asyncio.Lock()
    tracker.voice_sessions = {}
    tracker.stats_manager = MagicMock()
    tracker.stats_manager.add_voice_seconds = AsyncMock(side_effect=RuntimeError("DB"))
    tracker.stats_manager.transfer_daily_to_monthly = AsyncMock()

    await UserStatsTracker.daily_transfer.coro(tracker)

    tracker.stats_manager.transfer_daily_to_monthly.assert_not_awaited()
    assert tracker._pending_voice == {(123, date(2026, 9, 19)): 120}


@pytest.mark.asyncio
async def test_wrapped_post_uses_one_summary_and_link_button() -> None:
    """Карточка и кнопка относятся к одному снимку; упоминания выключены."""
    from utils.wrapped.builder import ServerWrapped

    tracker = UserStatsTracker.__new__(UserStatsTracker)
    channel = MagicMock()
    channel.send = AsyncMock()
    tracker._report_channel = MagicMock(return_value=channel)
    summary = ServerWrapped(
        "Август 2026", "monthly", 10, 60, 3601, 2,
        message_url="https://discord.com/channels/1/2/3",
    )
    tracker._server_summary = AsyncMock(return_value=summary)
    tracker._render_summary = AsyncMock(return_value=b"png")
    assert await tracker._post_server_wrapped("monthly", 2026, 8)
    tracker._server_summary.assert_awaited_once_with("monthly", 2026, 8)
    tracker._render_summary.assert_awaited_once_with(summary)
    sent = channel.send.await_args.kwargs
    assert sent["view"].children[0].url == summary.message_url
    assert sent["allowed_mentions"].everyone is False
    assert sent["allowed_mentions"].users is False


@pytest.mark.asyncio
async def test_wrapped_read_failure_never_sends_zero_card() -> None:
    tracker = UserStatsTracker.__new__(UserStatsTracker)
    channel = MagicMock()
    channel.send = AsyncMock()
    tracker._report_channel = MagicMock(return_value=channel)
    tracker._server_summary = AsyncMock(side_effect=RuntimeError("db"))
    with pytest.raises(RuntimeError):
        await tracker._post_server_wrapped("monthly", 2026, 8)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrapped_summary_passes_public_channel_and_reaction_filters() -> None:
    from types import SimpleNamespace

    tracker = UserStatsTracker.__new__(UserStatsTracker)
    guild = MagicMock()
    guild.id = 1
    guild.members = [SimpleNamespace(id=8, bot=True), SimpleNamespace(id=9, bot=False)]
    tracker.bot = MagicMock()
    tracker.bot.guilds = [guild]
    tracker.stats_manager = MagicMock()
    tracker.activity_manager = MagicMock()
    tracker.reactions_manager = MagicMock()
    tracker._footnote = MagicMock(return_value="PD Bot")
    settings = SimpleNamespace(
        user_stats=SimpleNamespace(top_limit=5, data_since="2026-06-01"),
        top_reactions=SimpleNamespace(ignored_message_ids=[20],
            ignore_role_reaction_message=True, ignore_bots=True, ignore_self_reactions=True),
    )
    with (
        patch("cogs.user_stats.get_settings", return_value=settings),
        patch("cogs.user_stats.public_message_channel_ids", return_value={10}),
        patch("cogs.user_stats.RoleReactionDataManager.get_message_info",
              AsyncMock(return_value=(10, 21))) as role_read,
        patch("cogs.user_stats.build_server_wrapped", AsyncMock()) as builder,
    ):
        await tracker._server_summary("monthly", 2026, 8)
    role_read.assert_awaited_once_with(1, strict=True)
    kwargs = builder.await_args.kwargs
    assert kwargs["allowed_channel_ids"] == {10}
    assert kwargs["excluded_message_ids"] == {20, 21}
    assert kwargs["excluded_user_ids"] == {8}
    assert kwargs["ignore_self_reactions"] is True

@pytest.mark.parametrize("scope,label", [("monthly","Август 2026"),("yearly","2026 год")])
async def test_wrapped_fetches_unique_avatars_from_both_rankings_and_awards(scope,label):
    from utils.wrapped.builder import ServerWrapped, NamedValue, Nomination
    tracker=UserStatsTracker.__new__(UserStatsTracker)
    guild=MagicMock()
    tracker.bot=MagicMock()
    tracker.bot.guilds=[guild]
    tracker._fetch_avatars=AsyncMock(return_value={1:b"avatar"})
    summary=ServerWrapped(label,scope,1,1,1,3,
        top_messages=[NamedValue(1,1)],top_voice=[NamedValue(2,1)],
        nominations=[Nomination("","Геймер",3,"1 ч"),Nomination("","По реакциям",1,"1")])
    with patch("cogs.user_stats.render_server_card",return_value=b"png") as render:
        assert await tracker._render_summary(summary) == b"png"
    tracker._fetch_avatars.assert_awaited_once_with([1,2,3],guild)
    assert render.call_args.args[2] == {1:b"avatar"}
