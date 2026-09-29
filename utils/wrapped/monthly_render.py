"""PNG месячного wrapped: адаптивная типографика и независимые колонки."""

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from matplotlib.ft2font import FT2Font
from PIL import Image, ImageDraw, ImageFont

from .builder import ServerWrapped

FONTS = Path(__file__).parent / "assets/fonts"
INK = "#111312"
PAPER = "#F0EFE7"
MUTED = "#A8ADA6"
LIME = "#CCFF66"
LILAC = "#C4B4F8"
WIDTH = 1200
LIMIT = 2**63 - 1


@dataclass(frozen=True)
class _Metric:
    """Значение хранится в исходных единицах, время — в секундах."""

    label: str
    current: int | None
    previous: int | None
    time: bool = False
    comparison_ready: bool = False


@dataclass(frozen=True)
class _Row:
    """Одна строка рейтинга."""

    name: str
    value: int


@dataclass(frozen=True)
class _CardData:
    """Данные для компоновки месячной карточки."""

    month: str
    year: int
    metrics: tuple[_Metric, ...]
    messages: tuple[_Row, ...] | None = ()
    voice: tuple[_Row, ...] | None = ()
    games: tuple[_Row, ...] | None = ()
    nominations: tuple[tuple[str, str, str], ...] | None = ()


def _valid(value: int | None) -> None:
    if value is not None and (type(value) is not int or not 0 <= value <= LIMIT):
        raise ValueError("Ожидается неотрицательное целое число в пределах SQLite INTEGER")


@lru_cache(maxsize=1)
def _supported_characters() -> set[int]:
    return set(FT2Font(str(FONTS / "Montserrat-Medium.ttf")).get_charmap())


def _clean(text: str) -> str:
    text = "".join(c if unicodedata.category(c)[0] != "C" else " " for c in text)
    text = "".join(
        c if ord(c) in _supported_characters() or c.isspace() else f"[U+{ord(c):04X}]" for c in text
    )
    return " ".join(text.split()) or "Без имени"


def _number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _value(value: int | None, time: bool = False) -> str:
    _valid(value)
    if value is None:
        return "Нет данных"
    if not time:
        return _number(value)
    if 0 < value < 60:
        return "< 1 мин"
    return f"{_number(value // 60)} мин"


def _change(metric: _Metric) -> str:
    _valid(metric.current)
    _valid(metric.previous)
    if metric.current is None:
        return "Данные недоступны"
    if not metric.comparison_ready or metric.previous is None:
        return "Нет сравнения"
    current, previous = metric.current, metric.previous
    if previous == 0:
        return "Ранее — 0" if current else "Без изменений"
    if current == previous:
        return "0%"
    delta = Decimal(current - previous) * 100 / Decimal(previous)
    if abs(delta) < Decimal("0.1"):
        return "Рост < 0,1%" if delta > 0 else "Снижение < 0,1%"
    rounded = delta.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{rounded:+,f}%".replace(",", " ").replace(".", ",").replace("-", "−")


@lru_cache(maxsize=256)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Montserrat-{'Bold' if bold else 'Medium'}.ttf"), size)


def _fit(
    text: str, width: int, size: int, minimum: int = 20, truncate: bool = False, bold: bool = False
) -> tuple[str, ImageFont.FreeTypeFont]:
    text = _clean(text)
    while size > minimum and _font(size, bold).getlength(text) > width:
        size -= 1
    font = _font(size, bold)
    if font.getlength(text) <= width:
        return text, font
    if not truncate:
        raise ValueError(f"Значение не помещается в отведённую область: {text}")
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…", font


@dataclass
class _Canvas:
    """Холст проверяет границы всех текстовых областей."""

    height: int
    image: Image.Image = field(init=False)
    draw: ImageDraw.ImageDraw = field(init=False)
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.image = Image.new("RGB", (WIDTH, self.height), INK)
        self.draw = ImageDraw.Draw(self.image)

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
        """Вписывает текст в заданную ширину без пересечения соседних колонок."""
        text, font = _fit(text, width, size, minimum, truncate, bold)
        bbox = self.draw.textbbox((0, 0), text, font=font)
        actual_width = int(bbox[2] - bbox[0])
        actual_height = int(bbox[3] - bbox[1])
        if right:
            x += width - actual_width
        if x < 0 or x + actual_width > WIDTH or y + actual_height > self.height:
            raise ValueError("Текст выходит за границы изображения")
        self.draw.text((x - bbox[0], y - bbox[1]), text, font=font, fill=color)
        self.boxes.append((x, y, x + actual_width, y + actual_height))

    def metric(self, metric: _Metric, x: int, y: int, color: str, index: int) -> None:
        """Рисует показатель с отдельными строками значения и динамики."""
        self.draw.rectangle((x, y, x + 542, y + 276), fill=color)
        self.text(x + 25, y + 25, f"0{index} / {metric.label.upper()}", 492, 23, INK)
        self.text(
            x + 25, y + 77, _value(metric.current, metric.time), 492, 65, INK, True, minimum=22
        )
        self.text(
            x + 25,
            y + 158,
            "—" if metric.current is None else _change(metric),
            492,
            43,
            INK,
            True,
            minimum=20,
        )
        if metric.comparison_ready and metric.previous is not None:
            caption = "Было: " + _value(metric.previous, metric.time)
        else:
            caption = "История неполная или недоступна"
        self.text(x + 25, y + 229, caption, 492, 21, INK, minimum=18)

    def ranking(
        self, x: int, y: int, title: str, rows: tuple[_Row, ...] | None, time: bool, accent: str
    ) -> None:
        """Размер строк постоянный; длинный ник не вытесняет число."""
        self.text(x, y, title, 516, 30, accent, True)
        if not rows:
            self.text(
                x,
                y + 65,
                "Данные недоступны" if rows is None else "Нет записей за период",
                516,
                23,
                MUTED,
            )
            return
        ranked = sorted(rows, key=lambda r: r.value, reverse=True)
        maximum = max(r.value for r in ranked)
        for i, row in enumerate(ranked):
            _valid(row.value)
            yy = y + 62 + i * 78
            self.text(x, yy, f"{i + 1:02}", 35, 20, MUTED)
            value = _value(row.value, time)
            _, value_font = _fit(value, 275, 23, 18)
            value_width = min(275, int(value_font.getlength(value)) + 3)
            name_width = 516 - 50 - value_width - 20
            self.text(x + 50, yy, row.name, name_width, 23, truncate=True, minimum=21)
            self.text(x + 516 - value_width, yy, value, value_width, 23, minimum=18, right=True)
            self.draw.rectangle((x + 50, yy + 43, x + 516, yy + 47), fill="#343831")
            if maximum and row.value:
                length = max(1, round(466 * row.value / maximum))
                self.draw.rectangle((x + 50, yy + 43, x + 50 + length, yy + 47), fill=accent)


def _render_layout(data: _CardData) -> _Canvas:
    """Строит PNG-холст из переданных данных, без запросов к БД или Discord."""
    if len(data.metrics) != 4:
        raise ValueError("Требуются четыре основных показателя")
    top_height = 72 + max(1, len(data.messages or ()), len(data.voice or ())) * 78
    bottom_y = 950 + top_height + 50
    bottom_height = max(
        110, 64 + len(data.games or ()) * 78, 64 + len(data.nominations or ()) * 104
    )
    height = bottom_y + bottom_height + 28
    canvas = _Canvas(height)
    canvas.draw.rectangle((0, 0, WIDTH, 291), fill=LIME)
    canvas.text(48, 32, "PD / WRAPPED", 470, 25, INK, True)
    canvas.text(40, 97, data.month.upper(), 1104, 125, INK, True, minimum=60)
    canvas.text(48, 243, f"ИТОГИ СЕРВЕРА · {data.year}", 1104, 25, INK, True)
    for i, metric in enumerate(data.metrics):
        canvas.metric(
            metric, 48 + (i % 2) * 562, 321 + (i // 2) * 297, PAPER if i in (0, 3) else LILAC, i + 1
        )
    canvas.ranking(48, 950, "По сообщениям", data.messages, False, LIME)
    canvas.ranking(636, 950, "По войсу", data.voice, True, LILAC)
    canvas.draw.line((48, bottom_y - 28, 1152, bottom_y - 28), fill="#555A51", width=2)
    canvas.ranking(48, bottom_y, "Игры", data.games, True, LIME)
    canvas.text(636, bottom_y, "Топ месяца", 516, 30, LILAC, True)
    if not data.nominations:
        canvas.text(
            636,
            bottom_y + 64,
            "Данные недоступны" if data.nominations is None else "Нет записей за период",
            516,
            23,
            MUTED,
        )
    for i, (label, name, detail) in enumerate(data.nominations or ()):
        yy = bottom_y + 62 + i * 104
        canvas.text(636, yy, label, 516, 19, MUTED, minimum=18, truncate=True)
        canvas.text(636, yy + 29, name, 516, 27, PAPER, True, truncate=True)
        canvas.text(636, yy + 66, detail, 516, 20, LILAC, minimum=18, truncate=True)
    return canvas


def render_monthly_card(summary: ServerWrapped, names: Callable[[int], str]) -> bytes:
    """Возвращает месячную карточку в PNG.

    Args:
        summary: Сводка с исходными секундами и доступными базами сравнения.
        names: Отображаемые имена участников.

    Returns:
        PNG шириной 1200 пикселей; высота зависит от количества строк.
    """
    month, year_text = summary.period_label.rsplit(" ", 1)
    metrics = tuple(
        _Metric(label, current, summary.previous.get(key), time, key in summary.previous)
        for label, current, key, time in (
            ("Сообщения", summary.total_messages, "messages", False),
            ("Войс", summary.total_voice_seconds, "voice", True),
            ("Игры", summary.total_game_seconds, "games", True),
            ("Активные участники", summary.active_users, "users", False),
        )
    )
    data = _CardData(
        month=month,
        year=int(year_text),
        metrics=metrics,
        messages=tuple(_Row(names(row.user_id), row.value) for row in summary.top_messages[:5]),
        voice=tuple(_Row(names(row.user_id), row.value) for row in summary.top_voice[:5]),
        games=tuple(_Row(name, seconds) for name, seconds in summary.top_games[:5]),
        nominations=tuple(
            (nom.title, names(nom.user_id) if nom.user_id is not None else "—", nom.detail)
            for nom in summary.nominations[:4]
        ),
    )
    buffer = BytesIO()
    _render_layout(data).image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
