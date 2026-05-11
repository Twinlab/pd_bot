"""Тесты эмбедов и форматирования длительности из ``utils.music.embeds``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest
import wavelink

from utils.music.embeds import (
    _track_source_label,
    added_to_queue_embed,
    create_embed,
    format_duration,
    now_playing_embed,
    queue_embed,
)


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


class TestCreateEmbed:
    """``create_embed`` принимает kwargs для разных секций эмбеда."""

    def test_minimal(self) -> None:
        e = create_embed("заголовок", "описание")
        assert e.title == "заголовок"
        assert e.description == "описание"

    def test_thumbnail_and_footer(self) -> None:
        e = create_embed("t", "d", thumbnail="https://example.com/img.png", footer="ft")
        assert e.thumbnail.url == "https://example.com/img.png"
        assert e.footer.text == "ft"

    def test_fields_tuple_list(self) -> None:
        fields = [("A", "1", True), ("B", "2", False)]
        e = create_embed("t", fields=fields)
        assert len(e.fields) == 2
        assert e.fields[0].name == "A" and e.fields[1].inline is False

    def test_extra_kwargs_become_inline_fields(self) -> None:
        e = create_embed("t", custom="value")
        assert e.fields[0].name == "custom"
        assert e.fields[0].value == "value"
        assert e.fields[0].inline is True


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


class TestNowPlayingEmbed:
    def test_no_track_returns_info_embed(self) -> None:
        player = _make_player(current=None)
        embed = now_playing_embed(player)
        assert "ничего не играет" in embed.title.lower()

    def test_playing_track_has_thumbnail_and_fields(self) -> None:
        track = _make_track(artwork="https://example.com/t.png")
        player = _make_player(current=track)
        embed = now_playing_embed(player)
        assert "Сейчас играет" in embed.title
        assert track.title in embed.description
        names = [f.name for f in embed.fields]
        assert "Длительность" in names
        assert "Источник" in names
        assert "Заказал" in names
        assert embed.thumbnail.url == "https://example.com/t.png"

    def test_paused_shows_pause_emoji(self) -> None:
        track = _make_track()
        player = _make_player(current=track, paused=True)
        embed = now_playing_embed(player)
        assert "⏸" in embed.title or "Пауза" in embed.title or "Сейчас" in embed.title

    def test_next_track_field_present_when_queue_not_empty(self) -> None:
        track = _make_track(title="Now")
        next_track = _make_track(title="Next")
        player = _make_player(current=track, queue_tracks=[next_track])
        embed = now_playing_embed(player)
        next_field = next((f for f in embed.fields if f.name == "Следующий"), None)
        assert next_field is not None
        assert "Next" in next_field.value


class TestAddedToQueueEmbed:
    def test_contains_track_metadata(self) -> None:
        track = _make_track(title="My Song")
        player = _make_player(current=None)
        embed = added_to_queue_embed(track, position=3, player=player)
        assert "My Song" in embed.description
        positions = [f.value for f in embed.fields if f.name == "Позиция"]
        assert positions == ["3"]


class TestQueueEmbed:
    def test_empty_queue_message(self) -> None:
        player = _make_player(current=None, queue_tracks=[])
        embed = queue_embed(player, page=1, page_size=10)
        assert "Очередь" in embed.title
        assert "пуста" in (embed.description or "").lower()

    def test_pagination(self) -> None:
        tracks = [_make_track(title=f"T{i}") for i in range(25)]
        player = _make_player(current=None, queue_tracks=tracks)
        embed_page1 = queue_embed(player, page=1, page_size=10)
        embed_page3 = queue_embed(player, page=3, page_size=10)
        assert "T0" in embed_page1.description
        assert "T9" in embed_page1.description
        assert "T24" in embed_page3.description
        assert "Страница 1/3" in (embed_page1.footer.text or "")
        assert "Страница 3/3" in (embed_page3.footer.text or "")

    def test_includes_current_track(self) -> None:
        current = _make_track(title="Now")
        tracks = [_make_track(title=f"T{i}") for i in range(3)]
        player = _make_player(current=current, queue_tracks=tracks)
        embed = queue_embed(player, page=1, page_size=10)
        assert "Now" in (embed.description or "")
