"""Тесты CV2-карточек и форматирования из ``utils.music.embeds``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest
import wavelink

from utils.music.embeds import (
    _track_source_label,
    added_playlist_card,
    added_to_queue_card,
    format_duration,
    status_card,
)
from utils.ui import colors
from utils.ui.testing import accent_colours, joined_text


class TestFormatDuration:
    """Длительность приходит из wavelink в миллисекундах."""

    @pytest.mark.parametrize(
        ("ms", "expected"),
        [
            (None, "LIVE"),
            (0, "00:00"),
            (-1, "00:00"),
            (1000, "00:01"),
            (59_000, "00:59"),
            (60_000, "01:00"),
            (125_000, "02:05"),
            (3_600_000, "01:00:00"),
            (3_725_000, "01:02:05"),
        ],
    )
    def test_known_values(self, ms: int | None, expected: str) -> None:
        assert format_duration(ms) == expected

    @pytest.mark.parametrize("bad", ["abc", object()])
    def test_invalid_input_returns_unknown(self, bad: object) -> None:
        assert format_duration(bad) == "?:??"  # type: ignore[arg-type]


class TestTrackSourceLabel:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("youtube", "YouTube"),
            ("youtubemusic", "YT Music"),
            ("spotify", "Spotify"),
            ("soundcloud", "SoundCloud"),
            ("applemusic", "Apple Music"),
            ("", "Unknown"),
        ],
    )
    def test_known_sources(self, source: str, expected: str) -> None:
        track = SimpleNamespace(source=source)
        assert _track_source_label(track) == expected  # type: ignore[arg-type]


def _make_track(**kwargs: object) -> MagicMock:
    """Удобный фабричный метод для мока wavelink.Playable."""
    track = MagicMock(spec=wavelink.Playable)
    track.title = kwargs.get("title", "Test Track")
    track.author = kwargs.get("author", "Author")
    track.length = kwargs.get("length", 125_000)
    track.uri = kwargs.get("uri", "https://example.com/v/1")
    track.identifier = kwargs.get("identifier", "id-1")
    track.source = kwargs.get("source", "youtube")
    track.artwork = kwargs.get("artwork", None)
    track.extras = SimpleNamespace(requester_id=kwargs.get("requester_id"))
    return track


def _make_player(
    *,
    current: MagicMock | None = None,
    queue_tracks: list[MagicMock] | None = None,
    paused: bool = False,
    volume: int = 50,
    queue_mode: object = wavelink.QueueMode.normal,
) -> MagicMock:
    """Фабричный метод для мока wavelink.Player."""
    player = MagicMock(spec=wavelink.Player)
    player.current = current
    player.paused = paused
    player.volume = volume
    player.connected = True
    queue_tracks = queue_tracks or []
    queue = MagicMock(spec=wavelink.Queue)
    queue.mode = queue_mode
    queue.is_empty = len(queue_tracks) == 0
    queue.__iter__ = lambda self: iter(queue_tracks)
    queue.__len__ = lambda self: len(queue_tracks)
    queue.peek = lambda idx=0: queue_tracks[idx]
    player.queue = queue
    guild = MagicMock(spec=discord.Guild)
    guild.get_member = MagicMock(return_value=None)
    player.guild = guild
    return player


def _thumbnail_count(view: discord.ui.LayoutView) -> int:
    """Сколько ``Thumbnail`` (внутри ``Section``) содержит CV2-карточка."""
    return sum(1 for c in view.walk_children() if isinstance(c, discord.ui.Thumbnail))


class TestStatusCard:
    """``status_card`` — CV2-карточка короткого статуса."""

    def test_minimal_uses_neutral_accent(self) -> None:
        view = status_card("⏸️ Пауза")
        assert "⏸️ Пауза" in joined_text(view)
        assert accent_colours(view) == [colors.NEUTRAL]

    def test_description_and_custom_accent(self) -> None:
        view = status_card("✅ Готово", "Подробности", colors.SUCCESS)
        text = joined_text(view)
        assert "✅ Готово" in text
        assert "Подробности" in text
        assert accent_colours(view) == [colors.SUCCESS]

    def test_no_description_block_when_empty(self) -> None:
        view = status_card("⏩ Перемотано")
        assert joined_text(view).count("\n") == 0


class TestAddedToQueueCard:
    def test_contains_metadata_and_success_accent(self) -> None:
        track = _make_track(title="My Song")
        player = _make_player(current=None)
        view = added_to_queue_card(track, position=3, player=player)
        text = joined_text(view)
        assert "My Song" in text
        assert "Позиция:** 3" in text
        assert accent_colours(view) == [colors.SUCCESS]

    def test_artwork_renders_thumbnail(self) -> None:
        track = _make_track(artwork="https://example.com/a.png")
        player = _make_player(current=None)
        view = added_to_queue_card(track, position=1, player=player)
        assert _thumbnail_count(view) == 1

    def test_without_artwork_no_thumbnail(self) -> None:
        track = _make_track(artwork=None)
        player = _make_player(current=None)
        view = added_to_queue_card(track, position=1, player=player)
        assert _thumbnail_count(view) == 0


class TestAddedPlaylistCard:
    def _make_playlist(self, name: str, tracks: list[MagicMock]) -> MagicMock:
        playlist = MagicMock(spec=wavelink.Playlist)
        playlist.name = name
        playlist.tracks = tracks
        return playlist

    def test_contains_name_and_count(self) -> None:
        first = _make_track(title="First", artwork="https://example.com/p.png")
        playlist = self._make_playlist("My Mix", [first, _make_track()])
        player = _make_player(current=None, queue_tracks=[first])
        view = added_playlist_card(playlist, added=2, player=player)
        text = joined_text(view)
        assert "My Mix" in text
        assert "2 трек" in text
        assert accent_colours(view) == [colors.SUCCESS]
        assert _thumbnail_count(view) == 1

    def test_empty_playlist_no_thumbnail(self) -> None:
        playlist = self._make_playlist("Empty", [])
        player = _make_player(current=None)
        view = added_playlist_card(playlist, added=0, player=player)
        assert _thumbnail_count(view) == 0
        assert "Empty" in joined_text(view)
