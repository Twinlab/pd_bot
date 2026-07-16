"""Утилиты отрисовки музыкального модуля.

Здесь живут две ветки представления плеера:

* классические :class:`discord.Embed` (``*_embed``) — используются, пока флаг
  ``settings.ui.cv2_music`` выключен;
* карточки Components V2 (``*_card``, :class:`discord.ui.LayoutView`) — новый
  стек за тем же флагом (Фаза 3 модернизации).

Длительности форматируются в ``MM:SS`` / ``HH:MM:SS`` в обеих ветках.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from utils.ui import colors

from .config import COLORS

if TYPE_CHECKING:
    import wavelink


def create_embed(
    title: str,
    description: str = "",
    color: discord.Color | None = None,
    **kwargs: Any,
) -> discord.Embed:
    """Создаёт и возвращает объект :class:`discord.Embed` с заданными параметрами.

    Args:
        title: Заголовок эмбеда.
        description: Описание эмбеда.
        color: Цвет эмбеда. По умолчанию — ``COLORS['DEFAULT']``.
        **kwargs: Опциональные параметры:
            - ``thumbnail`` (``str``): URL миниатюры справа.
            - ``image`` (``str``): URL большого изображения снизу.
            - ``footer`` (``str``): Текст футера.
            - ``author`` (``dict`` | ``str``): Информация об авторе.
                Если ``dict`` — ожидаются ключи ``name``, ``icon_url``, ``url``.
            - ``fields`` (``list[tuple[str, str, bool]]``): Список полей
                ``(name, value, inline)``.
            - Любые остальные kwargs добавляются как inline-поля.

    Returns:
        Сконфигурированный эмбед.
    """
    final_color = color if color is not None else COLORS["DEFAULT"]
    embed = discord.Embed(title=title, description=description, color=final_color)
    for name, value in kwargs.items():
        if value is None:
            continue
        if name == "thumbnail" and isinstance(value, str):
            embed.set_thumbnail(url=value)
        elif name == "footer" and isinstance(value, str):
            embed.set_footer(text=value)
        elif name == "image" and isinstance(value, str):
            embed.set_image(url=value)
        elif name == "author":
            if isinstance(value, dict):
                embed.set_author(
                    name=str(value.get("name", "")),
                    icon_url=value.get("icon_url"),
                    url=value.get("url"),
                )
            elif isinstance(value, str):
                embed.set_author(name=value)
        elif name == "fields" and isinstance(value, list):
            for field_data in value:
                if isinstance(field_data, tuple) and len(field_data) >= 2:
                    field_name = str(field_data[0])
                    field_value = str(field_data[1])
                    inline = (
                        field_data[2]
                        if len(field_data) > 2 and isinstance(field_data[2], bool)
                        else True
                    )
                    embed.add_field(name=field_name, value=field_value, inline=inline)
        else:
            embed.add_field(name=str(name), value=str(value), inline=True)
    return embed


def format_duration(milliseconds: int | float | None) -> str:
    """Форматирует длительность из миллисекунд в строку ``MM:SS`` или ``HH:MM:SS``.

    Wavelink хранит длительность треков именно в миллисекундах, поэтому новая
    подпись принимает миллисекунды (старая принимала секунды — это разница с
    предыдущей версией модуля).

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


def now_playing_embed(player: wavelink.Player) -> discord.Embed:
    """Эмбед "Сейчас играет" с обложкой и метаданными текущего трека."""
    track = player.current
    if track is None:
        return create_embed(
            "⏹️ Сейчас ничего не играет",
            "Используйте `/play <запрос>` чтобы добавить трек.",
            COLORS["INFO"],
        )

    state_emoji = "⏸️" if player.paused else "▶️"
    title = f"{state_emoji} Сейчас играет"
    description = f"**[{track.title}]({track.uri or 'https://discord.com'})**"
    if track.author:
        description += f"\n_{track.author}_"

    fields: list[tuple[str, str, bool]] = [
        ("Длительность", format_duration(track.length), True),
        ("Источник", _track_source_label(track), True),
        ("Заказал", _requester_mention(track, player.guild), True),
    ]
    if len(player.queue) > 0:
        next_track = player.queue.peek(0)
        fields.append(
            (
                "Следующий",
                f"[{next_track.title}]({next_track.uri or 'https://discord.com'})",
                False,
            )
        )

    return create_embed(
        title,
        description,
        COLORS["DEFAULT"],
        thumbnail=track.artwork,
        fields=fields,
        footer=_footer_for_player(player),
    )


def added_to_queue_embed(
    track: wavelink.Playable,
    position: int,
    player: wavelink.Player,
) -> discord.Embed:
    """Эмбед-ответ на ``/play`` — подтверждение добавления трека."""
    return create_embed(
        "✅ Добавлено в очередь",
        f"**[{track.title}]({track.uri or 'https://discord.com'})**",
        COLORS["SUCCESS"],
        thumbnail=track.artwork,
        fields=[
            ("Длительность", format_duration(track.length), True),
            ("Позиция", str(position), True),
            ("Заказал", _requester_mention(track, player.guild), True),
        ],
    )


def added_playlist_embed(
    playlist: wavelink.Playlist,
    added: int,
    player: wavelink.Player,
) -> discord.Embed:
    """Эмбед-ответ на загрузку плейлиста через ``/play``."""
    first = playlist.tracks[0] if playlist.tracks else None
    return create_embed(
        "🎶 Плейлист добавлен",
        f"**{playlist.name}** — {added} трек(ов)",
        COLORS["SUCCESS"],
        thumbnail=first.artwork if first else None,
        fields=[
            ("Заказал", _requester_mention(first, player.guild) if first else "—", True),
            ("В очереди всего", str(len(player.queue)), True),
        ],
    )


def queue_embed(
    player: wavelink.Player,
    page: int,
    page_size: int,
) -> discord.Embed:
    """Эмбед страницы очереди (используется ``QueueView``)."""
    tracks = list(player.queue)
    total = len(tracks)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    chunk = tracks[start:end]

    description_lines: list[str] = []
    if player.current is not None:
        state_emoji = "⏸️" if player.paused else "▶️"
        description_lines.append(
            f"{state_emoji} **Сейчас:** [{player.current.title}]"
            f"({player.current.uri or 'https://discord.com'}) "
            f"`{format_duration(player.current.length)}`"
        )
        description_lines.append("")

    if not chunk:
        description_lines.append("_Очередь пуста._")
    else:
        description_lines.append("**В очереди:**")
        for idx, track in enumerate(chunk, start=start + 1):
            description_lines.append(
                f"`{idx}.` [{track.title}]"
                f"({track.uri or 'https://discord.com'}) "
                f"`{format_duration(track.length)}`"
            )

    total_ms = sum(int(t.length or 0) for t in tracks)
    if player.current and player.current.length:
        total_ms += int(player.current.length)

    return create_embed(
        "🎵 Очередь воспроизведения",
        "\n".join(description_lines),
        COLORS["DEFAULT"],
        footer=(
            f"Страница {page}/{total_pages} · "
            f"всего треков: {total + (1 if player.current else 0)} · "
            f"общая длительность: {format_duration(total_ms)}"
        ),
    )


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
# Components V2 — карточки (за флагом settings.ui.cv2_music)
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
