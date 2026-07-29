"""Тесты CV2-компонентов из ``utils.music.ui``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import wavelink

from utils.music.player import MusicPlayer
from utils.music.ui import (
    NowPlayingView,
    QueueLayoutView,
    SearchLayoutView,
    SearchSelect,
    build_now_playing_container,
    now_playing_static_view,
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
    type(player).current = property(lambda self, _t=current: _t)  # type: ignore[assignment]
    type(player).paused = property(lambda self, _v=paused: _v)  # type: ignore[assignment]
    type(player).connected = property(lambda self, _c=connected: _c)  # type: ignore[assignment]
    type(player).volume = property(lambda self, _v=volume: _v)  # type: ignore[assignment]

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
    type(player).guild = property(lambda self, _g=guild: _g)  # type: ignore[assignment]
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
