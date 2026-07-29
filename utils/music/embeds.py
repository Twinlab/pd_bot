"""Карточки Components V2 и форматирование данных музыкального модуля."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from utils.ui import colors

if TYPE_CHECKING:
    import wavelink


def format_duration(milliseconds: int | float | None) -> str:
    """Форматирует длительность из миллисекунд в строку ``MM:SS`` или ``HH:MM:SS``.

    Wavelink хранит длительность треков в миллисекундах.

    Args:
        milliseconds: Длительность в миллисекундах. ``None`` означает прямую
            трансляцию (livestream).

    Returns:
        Строка длительности. ``"LIVE"`` для прямых трансляций (``None``),
        ``"00:00"`` для нулевых/отрицательных значений,
        ``"?:??"`` при ошибке преобразования.
    """
    if milliseconds is None:
        return "LIVE"
    try:
        total_seconds = int(float(milliseconds) // 1000)
        if total_seconds <= 0:
            return "00:00"
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "?:??"


def _track_source_label(track: wavelink.Playable) -> str:
    """Возвращает человекочитаемое название источника трека."""
    source = (track.source or "").lower()
    return {
        "youtube": "YouTube",
        "youtubemusic": "YT Music",
        "soundcloud": "SoundCloud",
        "spotify": "Spotify",
        "applemusic": "Apple Music",
        "deezer": "Deezer",
        "yandexmusic": "Yandex Music",
        "bandcamp": "Bandcamp",
        "twitch": "Twitch",
        "vimeo": "Vimeo",
        "http": "HTTP",
    }.get(source, source.title() or "Unknown")


def _requester_mention(track: wavelink.Playable, guild: discord.Guild | None) -> str:
    """Возвращает упоминание пользователя, заказавшего трек, либо ``"—"``."""
    requester_id: int | None = getattr(track.extras, "requester_id", None)
    if requester_id is None or guild is None:
        return "—"
    member = guild.get_member(int(requester_id))
    return member.mention if member else f"<@{requester_id}>"


def _footer_for_player(player: wavelink.Player) -> str:
    """Текст футера для now-playing: режим повтора, громкость, длина очереди."""
    import wavelink as _wl

    mode_labels = {
        _wl.QueueMode.normal: "повтор: выкл",
        _wl.QueueMode.loop: "повтор: трек",
        _wl.QueueMode.loop_all: "повтор: очередь",
    }
    mode_text = mode_labels.get(player.queue.mode, "повтор: ?")
    return f"{mode_text} · громкость: {player.volume}% · в очереди: {len(player.queue)}"


# ---------------------------------------------------------------------------
# Components V2 cards
# ---------------------------------------------------------------------------

# Тонкий разделитель между метаданными в одну строку (узкий пробел вокруг точки).
_DOT = "\u2002·\u2002"


def _card_view(container: discord.ui.Container) -> discord.ui.LayoutView:
    """Оборачивает контейнер в неинтерактивный ``LayoutView`` без таймаута."""
    view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


def _heading_block(
    container: discord.ui.Container,
    text: str,
    thumbnail: str | None,
) -> None:
    """Добавляет заголовок: ``Section`` с обложкой справа либо обычный ``TextDisplay``."""
    if thumbnail:
        container.add_item(discord.ui.Section(text, accessory=discord.ui.Thumbnail(thumbnail)))
    else:
        container.add_item(discord.ui.TextDisplay(text))


def status_card(
    title: str,
    description: str = "",
    accent: discord.Colour | int | None = None,
) -> discord.ui.LayoutView:
    """CV2-карточка короткого статуса (пауза/скип/громкость и т.п.).

    Args:
        title: Заголовок статуса (с эмодзи).
        description: Необязательная вторая строка.
        accent: Цвет акцентной полосы. ``None`` — нейтральный тон.

    Returns:
        Неинтерактивный ``LayoutView`` с единственным контейнером.
    """
    container: discord.ui.Container = discord.ui.Container(
        accent_colour=accent if accent is not None else colors.NEUTRAL
    )
    container.add_item(discord.ui.TextDisplay(f"### {title}"))
    if description:
        container.add_item(discord.ui.TextDisplay(description))
    return _card_view(container)


def added_to_queue_card(
    track: wavelink.Playable,
    position: int,
    player: wavelink.Player,
) -> discord.ui.LayoutView:
    """CV2-карточка подтверждения добавления трека в очередь."""
    text = (
        "### ✅ Добавлено в очередь\n"
        f"**[{track.title}]({track.uri or 'https://discord.com'})**\n"
        f"**Длительность:** {format_duration(track.length)}{_DOT}"
        f"**Позиция:** {position}{_DOT}"
        f"**Заказал:** {_requester_mention(track, player.guild)}"
    )
    container: discord.ui.Container = discord.ui.Container(accent_colour=colors.SUCCESS)
    _heading_block(container, text, track.artwork)
    return _card_view(container)


def added_playlist_card(
    playlist: wavelink.Playlist,
    added: int,
    player: wavelink.Player,
) -> discord.ui.LayoutView:
    """CV2-карточка подтверждения добавления плейлиста."""
    first = playlist.tracks[0] if playlist.tracks else None
    text = (
        "### 🎶 Плейлист добавлен\n"
        f"**{playlist.name}** — {added} трек(ов)\n"
        f"**Заказал:** {_requester_mention(first, player.guild) if first else '—'}{_DOT}"
        f"**В очереди всего:** {len(player.queue)}"
    )
    container: discord.ui.Container = discord.ui.Container(accent_colour=colors.SUCCESS)
    _heading_block(container, text, first.artwork if first else None)
    return _card_view(container)
