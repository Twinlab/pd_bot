"""Тесты CV2-компонентов из ``utils.music.ui``."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import wavelink

from utils.music.player import MusicPlayer
from utils.music.ui import (
    NowPlayingView,
    QueueLayoutView,
    SearchLayoutView,
    SearchSelect,
    build_now_playing_container,
    finish_now_playing,
    now_playing_static_view,
    refresh_now_playing,
)
from utils.ui import colors
from utils.ui.testing import accent_colours, joined_text


class TestSearchSelect:
    def test_builds_options_from_tracks(self) -> None:
        tracks = []
        for i in range(5):
            t = MagicMock(spec=wavelink.Playable)
            t.title = f"Title {i}"
            t.author = "Author"
            t.length = 60_000
            tracks.append(t)
        select = SearchSelect(tracks, requester_id=1)
        assert len(select.options) == 5
        assert select.options[0].label == "Title 0"

    def test_truncates_long_labels(self) -> None:
        t = MagicMock(spec=wavelink.Playable)
        t.title = "X" * 200
        t.author = "Author"
        t.length = 1000
        select = SearchSelect([t], requester_id=1)
        assert len(select.options[0].label) == 100

    def test_only_first_25_tracks_used(self) -> None:
        tracks = []
        for i in range(30):
            t = MagicMock(spec=wavelink.Playable)
            t.title = str(i)
            t.author = "A"
            t.length = 1000
            tracks.append(t)
        select = SearchSelect(tracks, requester_id=1)
        # Discord ограничивает Select до 25 опций.
        assert len(select.options) == 25

    async def test_callback_rejects_non_requester(self) -> None:
        t = MagicMock(spec=wavelink.Playable)
        t.title = "X"
        t.author = "A"
        t.length = 1000
        select = SearchSelect([t], requester_id=42)
        select._values = ["0"]  # имитируем выбор

        # Делаем фейковый interaction от другого пользователя.
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 999
        interaction.response.send_message = MagicMock()

        async def _send(*_a: object, **_kw: object) -> None:
            return None

        interaction.response.send_message.side_effect = _send
        await select.callback(interaction)
        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True


def _make_track(**kwargs: object) -> MagicMock:
    """Мок ``wavelink.Playable`` с атрибутами, нужными CV2-вью."""
    track = MagicMock(spec=wavelink.Playable)
    track.title = kwargs.get("title", "Track")
    track.author = kwargs.get("author", "Author")
    track.length = kwargs.get("length", 125_000)
    track.uri = kwargs.get("uri", "https://example.com/v/1")
    track.source = kwargs.get("source", "youtube")
    track.artwork = kwargs.get("artwork", None)
    track.extras = SimpleNamespace(requester_id=None)
    return track


def _cv2_player(
    *,
    current: object = None,
    queue_tracks: list[MagicMock] | None = None,
    paused: bool = False,
    queue_mode: object = wavelink.QueueMode.normal,
    connected: bool = True,
    volume: int = 50,
) -> MusicPlayer:
    """Stub :class:`MusicPlayer` с очередью-списком и гильдией для CV2-вью."""
    player = MusicPlayer.__new__(MusicPlayer)
    player.text_channel = None
    player.now_playing_message = None
    player.now_playing_view = None
    player.now_playing_lock = asyncio.Lock()
    player._current = current
    player._paused = paused
    player._connected = connected
    player._volume = volume
    player.channel = MagicMock(spec=discord.VoiceChannel)

    tracks = queue_tracks or []
    queue = MagicMock(spec=wavelink.Queue)
    queue.mode = queue_mode
    queue.__len__ = lambda self, _t=tracks: len(_t)
    queue.__iter__ = lambda self, _t=tracks: iter(_t)
    queue.is_empty = len(tracks) == 0
    queue.peek = lambda idx=0, _t=tracks: _t[idx]
    player.queue = queue

    guild = MagicMock(spec=discord.Guild)
    guild.get_member = MagicMock(return_value=None)
    player._guild = guild
    return player


def _button_by_id(view: discord.ui.LayoutView, custom_id: str) -> discord.ui.Button:
    for child in view.walk_children():
        if isinstance(child, discord.ui.Button) and child.custom_id == custom_id:
            return child
    raise AssertionError(f"button {custom_id} not found")


class TestBuildNowPlayingContainer:
    def test_nothing_playing(self) -> None:
        player = _cv2_player(current=None)
        view: discord.ui.LayoutView = discord.ui.LayoutView()
        view.add_item(build_now_playing_container(player))
        assert "ничего не играет" in joined_text(view).lower()

    def test_shows_track_metadata(self) -> None:
        track = _make_track(title="Song", author="Band")
        player = _cv2_player(current=track)
        view = now_playing_static_view(player)
        text = joined_text(view)
        assert "Song" in text
        assert "Band" in text
        assert "02:05" in text
        assert accent_colours(view) == [colors.NEUTRAL]

    def test_next_track_line_when_queue_not_empty(self) -> None:
        current = _make_track(title="Now")
        nxt = _make_track(title="NextOne")
        player = _cv2_player(current=current, queue_tracks=[nxt])
        view = now_playing_static_view(player)
        assert "NextOne" in joined_text(view)

    def test_static_view_has_no_buttons(self) -> None:
        player = _cv2_player(current=_make_track())
        view = now_playing_static_view(player)
        buttons = [c for c in view.walk_children() if isinstance(c, discord.ui.Button)]
        assert buttons == []


class TestNowPlayingView:
    def test_all_controls_present(self) -> None:
        view = NowPlayingView(_cv2_player(current=_make_track()))
        for cid in (
            "music:pause_resume",
            "music:skip",
            "music:stop",
            "music:loop",
            "music:shuffle",
            "music:queue",
        ):
            assert _button_by_id(view, cid) is not None

    def test_no_current_disables_pause_skip(self) -> None:
        view = NowPlayingView(_cv2_player(current=None))
        assert _button_by_id(view, "music:pause_resume").disabled is True
        assert _button_by_id(view, "music:skip").disabled is True

    def test_pause_label_when_playing(self) -> None:
        view = NowPlayingView(_cv2_player(current=_make_track(), paused=False))
        btn = _button_by_id(view, "music:pause_resume")
        assert btn.label == "Пауза"
        assert btn.disabled is False

    def test_resume_label_when_paused(self) -> None:
        view = NowPlayingView(_cv2_player(current=_make_track(), paused=True))
        btn = _button_by_id(view, "music:pause_resume")
        assert btn.label == "Продолжить"
        assert btn.style == discord.ButtonStyle.success

    def test_loop_emoji_changes_with_mode(self) -> None:
        for mode, emoji in [
            (wavelink.QueueMode.normal, "🔁"),
            (wavelink.QueueMode.loop, "🔂"),
            (wavelink.QueueMode.loop_all, "🔁"),
        ]:
            view = NowPlayingView(_cv2_player(current=_make_track(), queue_mode=mode))
            assert str(_button_by_id(view, "music:loop").emoji) == emoji

    def test_shuffle_disabled_with_short_queue(self) -> None:
        view = NowPlayingView(_cv2_player(current=_make_track(), queue_tracks=[_make_track()]))
        assert _button_by_id(view, "music:shuffle").disabled is True

    def test_stop_disabled_when_disconnected(self) -> None:
        view = NowPlayingView(_cv2_player(current=_make_track(), connected=False))
        assert _button_by_id(view, "music:stop").disabled is True

    def test_render_is_idempotent(self) -> None:
        view = NowPlayingView(_cv2_player(current=_make_track()))
        view._render()
        view._render()
        # Повторный рендер не плодит дубликаты кнопок управления.
        ids = [c.custom_id for c in view.walk_children() if isinstance(c, discord.ui.Button)]
        assert ids.count("music:pause_resume") == 1


class TestMusicInteractions:
    @pytest.mark.parametrize(
        ("handler", "operation", "edits_card"),
        [
            ("handle_pause", "pause", True),
            ("handle_skip", "skip", False),
            ("handle_stop", "disconnect", True),
        ],
    )
    async def test_acknowledges_before_network_operation(
        self, handler: str, operation: str, edits_card: bool
    ) -> None:
        player = _cv2_player(current=_make_track())
        player.now_playing_message = MagicMock()
        player.now_playing_message.edit = AsyncMock()
        view = NowPlayingView(player)
        player.now_playing_view = view
        view._validate = AsyncMock(return_value=True)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.edit_message = AsyncMock()
        interaction.edit_original_response = AsyncMock()

        async def acknowledge() -> None:
            interaction.response.is_done.return_value = True

        async def network_operation(*args, **kwargs) -> None:
            assert interaction.response.is_done()
            interaction.response.defer.assert_awaited_once()

        interaction.response.defer = AsyncMock(side_effect=acknowledge)
        operation_mock = AsyncMock(side_effect=network_operation)
        setattr(player, operation, operation_mock)

        await getattr(view, handler)(interaction)

        operation_mock.assert_awaited_once()
        interaction.edit_original_response.assert_not_awaited()
        interaction.response.edit_message.assert_not_awaited()
        assert player.now_playing_message.edit.await_count == int(edits_card)


class TestSearchLayoutView:
    def _make_member(self) -> MagicMock:
        member = MagicMock(spec=discord.Member)
        member.id = 7
        return member

    def test_builds_select_with_options(self) -> None:
        tracks = [_make_track(title=f"T{i}") for i in range(3)]
        view = SearchLayoutView(MagicMock(), tracks, self._make_member(), "запрос")
        selects = [c for c in view.walk_children() if isinstance(c, SearchSelect)]
        assert len(selects) == 1
        assert len(selects[0].options) == 3
        assert "запрос" in joined_text(view)

    async def test_handle_selection_delegates_to_cog(self) -> None:
        cog = MagicMock()
        cog._enqueue_selected_track = AsyncMock()
        member = self._make_member()
        track = _make_track()
        view = SearchLayoutView(cog, [track], member, "q")
        interaction = MagicMock(spec=discord.Interaction)
        await view.handle_selection(interaction, track)
        cog._enqueue_selected_track.assert_awaited_once_with(interaction, track, member)


class TestQueueLayoutView:
    def _setup(self, queue_size: int, page: int, page_size: int = 10) -> QueueLayoutView:
        player = _cv2_player(queue_tracks=[_make_track(title=f"T{i}") for i in range(queue_size)])
        return QueueLayoutView(player, page=page, page_size=page_size)

    def test_total_pages(self) -> None:
        assert self._setup(21, 1)._total_pages == 3
        assert self._setup(10, 1)._total_pages == 1
        assert self._setup(0, 1)._total_pages == 1

    def test_prev_disabled_on_first_page(self) -> None:
        view = self._setup(30, 1)
        assert _button_by_id(view, "music:queue_prev").disabled is True

    def test_next_disabled_on_last_page(self) -> None:
        view = self._setup(25, 3)
        assert _button_by_id(view, "music:queue_next").disabled is True

    def test_no_pager_for_single_page(self) -> None:
        view = self._setup(5, 1)
        buttons = [c for c in view.walk_children() if isinstance(c, discord.ui.Button)]
        assert buttons == []

    def test_footer_shows_page_numbers(self) -> None:
        view = self._setup(25, 2)
        assert "Страница 2/3" in joined_text(view)

    def test_lists_tracks_for_page(self) -> None:
        view = self._setup(25, 1)
        text = joined_text(view)
        assert "T0" in text
        assert "T9" in text


class TestPanelLifecycle:
    def _player(self) -> MusicPlayer:
        player = _cv2_player(current=_make_track())
        player.text_channel = MagicMock(spec=discord.TextChannel)
        player.text_channel.send = AsyncMock()
        player.now_playing_message = MagicMock(spec=discord.Message)
        player.now_playing_message.edit = AsyncMock()
        player.now_playing_view = NowPlayingView(player)
        return player

    async def test_refresh_reuses_live_view_and_message(self) -> None:
        player = self._player()
        view = player.now_playing_view
        player._paused = True
        player.queue.mode = wavelink.QueueMode.loop_all

        assert await refresh_now_playing(player, create=True)

        assert player.now_playing_view is view
        assert _button_by_id(view, "music:pause_resume").label == "Продолжить"
        assert _button_by_id(view, "music:loop").label == "Повтор: очередь"
        player.now_playing_message.edit.assert_awaited_once_with(view=view)
        player.text_channel.send.assert_not_awaited()

    async def test_parallel_initial_publications_create_one_message(self) -> None:
        player = self._player()
        message = player.now_playing_message
        player.now_playing_message = None

        async def send(**kwargs):
            await asyncio.sleep(0)
            return message

        player.text_channel.send.side_effect = send
        await asyncio.gather(
            refresh_now_playing(player, create=True), refresh_now_playing(player, create=True)
        )
        player.text_channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()

    async def test_http_failure_keeps_controls_and_does_not_duplicate(self) -> None:
        player = self._player()
        previous = player.now_playing_view
        player.now_playing_message.edit.side_effect = discord.HTTPException(
            MagicMock(status=500), "unavailable"
        )

        assert not await refresh_now_playing(player, create=True)

        assert player.now_playing_view is previous
        assert not previous.is_finished()
        player.text_channel.send.assert_not_awaited()

    async def test_deleted_panel_can_be_recreated(self) -> None:
        player = self._player()
        player.now_playing_message.edit.side_effect = discord.NotFound(
            MagicMock(status=404), "deleted"
        )
        replacement = MagicMock(spec=discord.Message)
        player.text_channel.send.return_value = replacement

        assert await refresh_now_playing(player, create=True)
        assert player.now_playing_message is replacement
        player.text_channel.send.assert_awaited_once()

    async def test_finished_view_is_stopped_before_new_handlers_register(self) -> None:
        from discord.ui.view import ViewStore

        player = self._player()
        old_view = player.now_playing_view
        store = ViewStore(MagicMock())
        store.add_view(old_view, message_id=123)
        old_view.stop()

        async def edit(*, view):
            assert old_view.is_finished()
            store.add_view(view, message_id=123)

        player.now_playing_message.edit.side_effect = edit
        assert await refresh_now_playing(player)
        new_view = player.now_playing_view
        assert new_view is not old_view
        assert store._views[123][(2, "music:pause_resume")].view is new_view
        await old_view.on_timeout()
        assert player.now_playing_message.edit.await_count == 1
        new_view.stop()

    async def test_timeout_during_edit_cannot_close_refreshed_panel(self) -> None:
        from discord.ui.view import ViewStore

        player = self._player()
        old_view = player.now_playing_view
        store = ViewStore(MagicMock())
        store.add_view(old_view, message_id=123)
        timeout_task = None

        async def edit(*, view):
            nonlocal timeout_task
            if view is old_view:
                old_view._dispatch_timeout()
                timeout_task = next(
                    task
                    for task in asyncio.all_tasks()
                    if task.get_name() == f"discord-ui-view-timeout-{old_view.id}"
                )
                await asyncio.sleep(0)
            if not view.is_finished():
                store.add_view(view, message_id=123)

        player.now_playing_message.edit.side_effect = edit
        assert await refresh_now_playing(player)
        await timeout_task
        assert player.now_playing_view is not old_view
        assert not player.now_playing_view.is_finished()
        assert player.now_playing_message.edit.await_count == 2
        assert store._views[123][(2, "music:pause_resume")].view is player.now_playing_view
        player.now_playing_view.stop()

    async def test_stop_cannot_be_overwritten_by_old_timeout(self) -> None:
        player = self._player()
        old_view = player.now_playing_view
        await finish_now_playing(player, "Остановлено", "Начните с `/play`.")
        await old_view.on_timeout()

        assert player.now_playing_view is None
        assert old_view.is_finished()
        card = player.now_playing_message.edit.call_args.kwargs["view"]
        assert "Остановлено" in joined_text(card)
        assert not any(isinstance(item, discord.ui.Button) for item in card.walk_children())
        player.now_playing_message.edit.assert_awaited_once()

    async def test_queue_end_rechecks_state_after_waiting_for_edit(self) -> None:
        player = self._player()
        player._current = None
        await player.now_playing_lock.acquire()
        closing = asyncio.create_task(
            finish_now_playing(player, "Конец", "", only_if_idle=True)
        )
        await asyncio.sleep(0)
        player._current = _make_track(title="Next")
        player.now_playing_lock.release()
        await closing
        player.now_playing_message.edit.assert_not_awaited()
        assert not player.now_playing_view.is_finished()

    async def test_button_completion_renders_after_concurrent_refresh(self) -> None:
        player = self._player()
        view = player.now_playing_view
        view._validate = AsyncMock(return_value=True)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.response.is_done.return_value = True

        async def pause(paused):
            await refresh_now_playing(player)
            player._paused = paused

        player.pause = AsyncMock(side_effect=pause)
        await view.handle_pause(interaction)
        assert _button_by_id(player.now_playing_view, "music:pause_resume").label == "Продолжить"


class TestTemporaryMenuLifecycle:
    @pytest.mark.parametrize("kind", ["search", "queue"])
    async def test_timeout_removes_controls_and_explains_reopening(self, kind: str) -> None:
        member = MagicMock(spec=discord.Member)
        member.id = 7
        view = (
            SearchLayoutView(MagicMock(), [_make_track()], member, "q")
            if kind == "search"
            else QueueLayoutView(_cv2_player(queue_tracks=[_make_track()] * 15))
        )
        view.message = MagicMock(spec=discord.Message)
        view.message.edit = AsyncMock()
        await view.on_timeout()

        card = view.message.edit.call_args.kwargs["view"]
        assert ("/play" if kind == "search" else "/queue") in joined_text(card)
        assert not any(
            isinstance(item, (discord.ui.Button, discord.ui.Select)) for item in card.walk_children()
        )
        assert view.is_finished()

    async def test_completed_selection_wins_over_timeout_and_double_click(self) -> None:
        started = asyncio.Event()
        finish = asyncio.Event()
        cog = MagicMock()

        async def enqueue(*args):
            started.set()
            await finish.wait()
            return True

        cog._enqueue_selected_track = AsyncMock(side_effect=enqueue)
        member = MagicMock(spec=discord.Member)
        member.id = 7
        track = _make_track()
        view = SearchLayoutView(cog, [track], member, "q")
        view.message = MagicMock(spec=discord.Message)
        view.message.edit = AsyncMock()
        first = asyncio.create_task(view.handle_selection(MagicMock(), track))
        await started.wait()
        with patch("utils.music.ui.safe_send_error", new=AsyncMock()) as error:
            await view.handle_selection(MagicMock(), track)
            error.assert_awaited_once()
        timeout = asyncio.create_task(view.on_timeout())
        await asyncio.sleep(0)
        finish.set()
        await asyncio.gather(first, timeout)

        cog._enqueue_selected_track.assert_awaited_once()
        view.message.edit.assert_not_awaited()

    async def test_queue_acknowledges_before_waiting_for_timeout(self) -> None:
        view = QueueLayoutView(_cv2_player(queue_tracks=[_make_track()] * 15))
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        await view._lock.acquire()
        task = asyncio.create_task(view.change_page(interaction, 1))
        await asyncio.sleep(0)
        interaction.response.defer.assert_awaited_once()
        view._expired = True
        view._lock.release()
        with patch("utils.music.ui.safe_send_error", new=AsyncMock()) as error:
            await task
            error.assert_awaited_once()
        interaction.edit_original_response.assert_not_awaited()

    async def test_queue_button_binds_ephemeral_response(self) -> None:
        player = _cv2_player(current=_make_track())
        view = NowPlayingView(player)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.send_message = AsyncMock()
        interaction.original_response = AsyncMock()
        await view.handle_show_queue(interaction)
        queue_view = interaction.response.send_message.call_args.kwargs["view"]
        assert queue_view.message is interaction.original_response.return_value

    async def test_callback_error_uses_incident_reply(self) -> None:
        view = QueueLayoutView(_cv2_player())
        interaction = MagicMock(spec=discord.Interaction)
        with (
            patch("utils.music.ui.safe_send_error", new=AsyncMock()) as reply,
            patch("utils.music.ui.new_incident_id", return_value="music-test"),
        ):
            await view.on_error(interaction, RuntimeError("broken"), MagicMock())
        assert "music-test" in reply.call_args.args[1]
