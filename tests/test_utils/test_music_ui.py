"""Тесты View-классов из ``utils.music.ui``.

UI-логика модуля небольшая, но критичная: refresh() выставляет ``disabled``
кнопок и метки, а ``SearchSelect`` строит options из результатов поиска. Эти
куски легко проверить без живого Discord-окружения.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest
import wavelink

from utils.music.player import MusicPlayer
from utils.music.ui import PlayerControlView, QueueView, SearchSelect


def _stub_player(
    *,
    current: object = None,
    queue_size: int = 0,
    paused: bool = False,
    queue_mode: object = wavelink.QueueMode.normal,
    connected: bool = True,
) -> MusicPlayer:
    """Stub :class:`MusicPlayer` для unit-тестов View.

    Не вызываем ``__init__`` (он требует ``discord.Client``+``Connectable``), а
    собираем атрибуты вручную через ``__new__``.
    """
    player = MusicPlayer.__new__(MusicPlayer)

    # property current → подменяем на классе, чтобы геттер просто возвращал значение.
    type(player).current = property(  # type: ignore[assignment]
        lambda self, _t=current: _t
    )
    type(player).paused = property(  # type: ignore[assignment]
        lambda self, _v=paused: _v
    )
    type(player).connected = property(  # type: ignore[assignment]
        lambda self, _c=connected: _c
    )

    queue = MagicMock(spec=wavelink.Queue)
    queue.mode = queue_mode
    queue.__len__ = lambda self, _s=queue_size: _s
    queue.is_empty = queue_size == 0
    player.queue = queue
    return player


class TestPlayerControlViewRefresh:
    """``refresh()`` синхронизирует кнопки с текущим состоянием плеера."""

    def _get_button(self, view: discord.ui.View, custom_id: str) -> discord.ui.Button:
        for child in view.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == custom_id:
                return child
        raise AssertionError(f"button {custom_id} not found")

    def test_no_current_disables_pause_skip(self) -> None:
        view = PlayerControlView(_stub_player(current=None, queue_size=0))
        assert self._get_button(view, "music:pause_resume").disabled
        assert self._get_button(view, "music:skip").disabled

    def test_pause_label_when_playing(self) -> None:
        track = SimpleNamespace()
        view = PlayerControlView(_stub_player(current=track, paused=False))
        btn = self._get_button(view, "music:pause_resume")
        assert btn.disabled is False
        assert btn.label == "Пауза"

    def test_resume_label_when_paused(self) -> None:
        track = SimpleNamespace()
        view = PlayerControlView(_stub_player(current=track, paused=True))
        btn = self._get_button(view, "music:pause_resume")
        assert btn.label == "Продолжить"
        assert btn.style == discord.ButtonStyle.success

    def test_loop_emoji_changes_with_mode(self) -> None:
        for mode, emoji in [
            (wavelink.QueueMode.normal, "🔁"),
            (wavelink.QueueMode.loop, "🔂"),
            (wavelink.QueueMode.loop_all, "🔁"),
        ]:
            view = PlayerControlView(_stub_player(queue_mode=mode))
            btn = self._get_button(view, "music:loop")
            assert str(btn.emoji) == emoji

    def test_shuffle_disabled_with_short_queue(self) -> None:
        view = PlayerControlView(_stub_player(queue_size=1))
        assert self._get_button(view, "music:shuffle").disabled is True

    def test_shuffle_enabled_with_enough_tracks(self) -> None:
        view = PlayerControlView(_stub_player(queue_size=3))
        assert self._get_button(view, "music:shuffle").disabled is False

    def test_queue_disabled_when_nothing(self) -> None:
        view = PlayerControlView(_stub_player(current=None, queue_size=0))
        assert self._get_button(view, "music:queue").disabled is True

    def test_stop_disabled_when_disconnected(self) -> None:
        view = PlayerControlView(_stub_player(connected=False))
        assert self._get_button(view, "music:stop").disabled is True


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


class TestQueueViewPagination:
    def _setup_view(self, queue_size: int, page: int, page_size: int = 10) -> QueueView:
        player = _stub_player(queue_size=queue_size)
        return QueueView(player, page=page, page_size=page_size)

    def test_prev_disabled_on_first_page(self) -> None:
        view = self._setup_view(queue_size=30, page=1)
        prev_btn = next(
            c
            for c in view.children
            if isinstance(c, discord.ui.Button) and c.custom_id == "music:queue_prev"
        )
        assert prev_btn.disabled is True

    def test_next_disabled_on_last_page(self) -> None:
        view = self._setup_view(queue_size=25, page=3)
        next_btn = next(
            c
            for c in view.children
            if isinstance(c, discord.ui.Button) and c.custom_id == "music:queue_next"
        )
        assert next_btn.disabled is True

    def test_total_pages_calculation(self) -> None:
        view = self._setup_view(queue_size=21, page=1, page_size=10)
        assert view._total_pages == 3
        view2 = self._setup_view(queue_size=10, page=1, page_size=10)
        assert view2._total_pages == 1
        view3 = self._setup_view(queue_size=0, page=1, page_size=10)
        assert view3._total_pages == 1
