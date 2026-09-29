"""Единый PNG-дизайн серверных и личных wrapped-карточек."""

from collections.abc import Callable
from io import BytesIO

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from utils.wrapped.builder import (
    PersonalWrapped,
    ServerWrapped,
)
from utils.wrapped.monthly_render import (
    _Canvas as _BaseCanvas,
)
from utils.wrapped.monthly_render import (
    _change,
    _fit,
    _Metric,
    _number,
    _valid,
)

INK = "#101010"
PAPER = "#FFFFFF"
MUTED = "#A9A9A9"
RED = "#FF424B"
WHITE = "#FFFFFF"


class _Canvas(_BaseCanvas):
    """Холст в палитре wrapped."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self.image.paste(INK, (0, 0, 1200, self.height))

    def text(
        self,
        x: int,
        y: int,
        text: str,
        width: int,
        size: int = 24,
        color: str = PAPER,
        bold: bool = False,
        truncate: bool = False,
        minimum: int = 20,
        right: bool = False,
    ) -> None:
        super().text(x, y, text, width, size, color, bold, truncate, minimum, right)


def _center(
    canvas: _Canvas,
    x: int,
    y: int,
    text: str,
    width: int,
    size: int,
    color: str = PAPER,
    bold: bool = False,
) -> None:
    fitted, font = _fit(text, width, size, 22, True, bold)
    box = canvas.draw.textbbox((0, 0), fitted, font=font)
    actual = box[2] - box[0]
    canvas.text(x + (width - actual) // 2, y, fitted, actual + 2, font.size, color, bold)


def _avatar(
    canvas: _Canvas,
    x: int,
    y: int,
    size: int,
    user_id: int | None,
    name: str,
    avatars: dict[int, Image.Image],
) -> None:
    source = avatars.get(user_id) if user_id is not None else None
    mask = Image.new("L", (size, size))
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    before = len(canvas.boxes)
    if source is None:
        canvas.draw.ellipse((x, y, x + size, y + size), fill="#3B3B3B")
        fitted, font = _fit(name[:1].upper() or "?", size - 10, size // 2, 14, True, True)
        bbox = canvas.draw.textbbox((0, 0), fitted, font=font)
        canvas.text(
            x + (size - (bbox[2] - bbox[0])) // 2,
            y + (size - (bbox[3] - bbox[1])) // 2,
            fitted,
            size - 8,
            font.size,
            PAPER,
            True,
            minimum=14,
        )
    else:
        tile = ImageOps.fit(source.convert("RGB"), (size, size), method=Image.Resampling.LANCZOS)
        canvas.image.paste(tile, (x, y), mask)
    del canvas.boxes[before:]
    canvas.boxes.append((x, y, x + size, y + size))


def _duration(seconds: int) -> str:
    _valid(seconds)
    if 0 < seconds < 60:
        return "< 1 мин"
    hours, minutes = divmod(seconds // 60, 60)
    if not hours:
        return f"{minutes} мин"
    return f"{_number(hours)} ч" + (f" {minutes} мин" if minutes else "")


def _value(value: int, time: bool) -> str:
    _valid(value)
    return _duration(value) if time else _number(value)


def _header(
    canvas: _Canvas,
    year: int,
    personal: bool = False,
    name: str = "",
    month: str | None = None,
) -> None:
    canvas.draw.rectangle((0, 0, 1200, 309), fill=RED)
    canvas.text(48, 32, "PD / WRAPPED", 410, 25, PAPER, True)
    if personal:
        _center(canvas, 48, 89, str(year), 1104, 162, PAPER, True)
        _center(canvas, 48, 263, "ТВОЙ ГОД", 1104, 25, PAPER, True)
    else:
        canvas.text(
            39,
            89,
            month.upper() if month else str(year),
            1104,
            125 if month else 162,
            PAPER,
            True,
            minimum=60,
        )
        subtitle = f"ИТОГИ СЕРВЕРА · {year}" if month else "ИТОГИ СЕРВЕРА"
        canvas.text(48, 263, subtitle, 1104, 25, PAPER, True)


def _metrics(
    canvas: _Canvas, y: int, items: tuple[tuple[str, str, int, bool], ...], previous: dict[str, int]
) -> int:
    pair_y = y
    for row in range(2):
        pair = items[row * 2 : row * 2 + 2]
        has_comparison = any(key in previous for key, _, _, _ in pair)
        height = 264 if has_comparison else 184
        for col, (key, label, value, time) in enumerate(pair):
            x = 48 + col * 562
            color = PAPER
            canvas.draw.rectangle((x, pair_y, x + 542, pair_y + height), fill=color)
            canvas.text(x + 25, pair_y + 25, label.upper(), 492, 23, INK)
            canvas.text(x + 25, pair_y + 78, _value(value, time), 492, 70, INK, True)
            if key in previous:
                canvas.text(
                    x + 25,
                    pair_y + 155,
                    _change(_Metric(label, value, previous[key], time, True)),
                    492,
                    39,
                    INK,
                    True,
                )
                canvas.text(
                    x + 25, pair_y + 220, "Было: " + _value(previous[key], time), 492, 21, INK
                )
        pair_y += height + 20
    return pair_y


def _metrics_height(items: tuple[tuple[str, str, int, bool], ...], previous: dict[str, int]) -> int:
    return sum(284 if any(row[0] in previous for row in items[i : i + 2]) else 204 for i in (0, 2))


def _ranking(
    canvas: _Canvas,
    x: int,
    y: int,
    title: str,
    rows: list[tuple[str, int]],
    time: bool,
    accent: str,
    width: int = 516,
    user_ids: list[int] | None = None,
    avatars: dict[int, Image.Image] | None = None,
) -> None:
    canvas.text(x, y, title, width, 30, accent, True)
    if not rows:
        canvas.text(x, y + 62, "Нет записей за год", width, 23, MUTED)
        return
    ranked = sorted(enumerate(rows), key=lambda row: row[1][1], reverse=True)[:5]
    maximum = max(value for _, (_, value) in ranked)
    for i, (original_index, (name, value)) in enumerate(ranked):
        _valid(value)
        yy = y + 62 + i * 78
        caption = _value(value, time)
        _, font = _fit(caption, min(290, width // 2), 23, 18)
        vw = min(290, int(font.getlength(caption)) + 3)
        canvas.text(x, yy, f"{i + 1:02}", 35, 20, MUTED)
        name_x = x + 50
        if user_ids is not None:
            _avatar(
                canvas,
                x + 43,
                yy - 5,
                44,
                user_ids[original_index],
                name,
                avatars or {},
            )
            name_x = x + 101
        canvas.text(name_x, yy, name, width - (name_x - x) - 20 - vw, 23, truncate=True, minimum=18)
        canvas.text(x + width - vw, yy, caption, vw, 23, minimum=18, right=True)
        canvas.draw.rectangle((name_x, yy + 43, x + width, yy + 47), fill="#343434")
        if maximum and value:
            length = max(1, round((width - (name_x - x)) * value / maximum))
            canvas.draw.rectangle((name_x, yy + 43, name_x + length, yy + 47), fill=accent)


def _server(
    summary: ServerWrapped,
    names: dict[int, str],
    avatars: dict[int, Image.Image],
) -> _Canvas:
    monthly = summary.scope == "monthly"
    year = int(summary.period_label.split()[-1 if monthly else 0])
    previous = summary.previous
    items = (
        ("messages", "Сообщения", summary.total_messages, False),
        ("voice", "Войс", summary.total_voice_seconds, True),
        ("games", "Игры", summary.total_game_seconds, True),
        ("users", "Активные участники", summary.active_users, False),
    )
    top_y = 340 + _metrics_height(items, previous) + 36
    top_count = max(1, min(5, len(summary.top_messages)), min(5, len(summary.top_voice)))
    bottom_y = top_y + 72 + top_count * 78 + 48
    bottom_height = max(
        130, 64 + min(5, len(summary.top_games)) * 78, 64 + min(4, len(summary.nominations)) * 104
    )
    canvas = _Canvas(bottom_y + bottom_height + 28)
    _header(canvas, year, month=summary.period_label.rsplit(" ", 1)[0] if monthly else None)
    _metrics(canvas, 340, items, previous)
    _ranking(
        canvas,
        48,
        top_y,
        "По сообщениям",
        [(names.get(n.user_id, f"ID {n.user_id}"), n.value) for n in summary.top_messages],
        False,
        RED,
        user_ids=[n.user_id for n in summary.top_messages],
        avatars=avatars,
    )
    _ranking(
        canvas,
        636,
        top_y,
        "По войсу",
        [(names.get(n.user_id, f"ID {n.user_id}"), n.value) for n in summary.top_voice],
        True,
        WHITE,
        user_ids=[n.user_id for n in summary.top_voice],
        avatars=avatars,
    )
    canvas.draw.line((48, bottom_y - 28, 1152, bottom_y - 28), fill="#555555", width=2)
    _ranking(canvas, 48, bottom_y, "Игры" if monthly else "Игры года", summary.top_games, True, RED)
    canvas.text(636, bottom_y, "Топ месяца" if monthly else "Топ года", 516, 30, WHITE, True)
    if not summary.nominations:
        canvas.text(636, bottom_y + 62, "Нет записей за год", 516, 23, MUTED)
    for i, nomination in enumerate(summary.nominations[:4]):
        yy = bottom_y + 62 + i * 104
        canvas.text(636, yy, nomination.title, 516, 19, MUTED, minimum=18, truncate=True)
        name = names.get(nomination.user_id, f"ID {nomination.user_id}")
        _avatar(canvas, 636, yy + 29, 56, nomination.user_id, name, avatars)
        canvas.text(710, yy + 29, name, 442, 27, PAPER, True, truncate=True)
        canvas.text(710, yy + 66, nomination.detail, 442, 20, WHITE, minimum=18, truncate=True)
    return canvas


def _personal(
    summary: PersonalWrapped,
    name: str,
    avatars: dict[int, Image.Image],
) -> _Canvas:
    year = int(summary.period_label.split()[0])
    previous = summary.previous
    items = (
        ("messages", "Сообщения", summary.messages, False),
        ("voice", "Войс", summary.voice_seconds, True),
        ("games", "Игры", summary.game_seconds, True),
        ("reactions", "Получено реакций", summary.reactions_received, False),
    )
    ranks = [
        (rank, label)
        for rank, label in (
            (summary.message_rank, "по сообщениям"),
            (summary.voice_rank, "по войсу"),
            (summary.reaction_rank, "по реакциям"),
        )
        if rank is not None
    ]
    metrics_y = 630
    ranks_y = metrics_y + _metrics_height(items, previous) + 32
    games_y = ranks_y + (202 if ranks else 0)
    canvas = _Canvas(games_y + 72 + max(1, min(5, len(summary.top_games))) * 78 + 38)
    _header(canvas, year, True, name)
    _avatar(canvas, 528, 342, 144, summary.user_id, name, avatars)
    _center(canvas, 48, 518, name, 1104, 67, PAPER, True)
    _metrics(canvas, metrics_y, items, previous)
    if ranks:
        _center(canvas, 48, ranks_y, "Твои места на сервере", 1104, 28, PAPER, True)
        column_width = 1104 // len(ranks)
        for i, (rank, label) in enumerate(ranks):
            x = 48 + i * column_width
            _center(canvas, x, ranks_y + 56, f"#{rank}", column_width, 61, RED, True)
            _center(canvas, x, ranks_y + 132, label, column_width, 22, MUTED)
    _ranking(canvas, 48, games_y, "Твои игры", summary.top_games, True, WHITE, width=1104)
    return canvas


def _decode_avatars(avatars: dict[int, bytes]) -> dict[int, Image.Image]:
    result = {}
    for user_id, raw in avatars.items():
        try:
            with Image.open(BytesIO(raw)) as source:
                result[user_id] = ImageOps.exif_transpose(source).convert("RGB")
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            # Неудачная загрузка аватара не должна отменять готовый отчёт.
            continue
    return result


def _png(canvas: _Canvas) -> bytes:
    output = BytesIO()
    canvas.image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_server(
    summary: ServerWrapped,
    names: Callable[[int], str],
    avatars: dict[int, bytes] | None = None,
) -> bytes:
    """Рисует серверный wrapped, сопоставляя аватары по ID участников."""
    ids = {row.user_id for row in [*summary.top_messages, *summary.top_voice]}
    ids.update(n.user_id for n in summary.nominations if n.user_id is not None)
    return _png(_server(summary, {uid: names(uid) for uid in ids}, _decode_avatars(avatars or {})))


def render_personal(
    summary: PersonalWrapped,
    name: str,
    avatar: bytes | None = None,
) -> bytes:
    """Рисует личный wrapped с центральным выравниванием профиля и мест."""
    avatars = _decode_avatars({summary.user_id: avatar} if avatar else {})
    return _png(_personal(summary, name, avatars))
