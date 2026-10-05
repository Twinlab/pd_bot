"""Рендер цитаты в WebP без Discord, сети и записи файлов."""

from __future__ import annotations

import hashlib
import io
import math
import re
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from utils.time_utils import MOSCOW_TZ

_ASSETS = Path(__file__).resolve().parents[1] / "wrapped" / "assets"
_WIDTH = 1200
_MAX_HEIGHT = 1200
_MIN_FONT_SIZE = 32
_MAX_AVATAR_BYTES = 2 * 1024 * 1024
_MAX_AVATAR_PIXELS = 4 * 1024 * 1024
_BG = "#101014"
_FG = "#F5F2EE"
_MUTED = "#A9A7AE"
_RED = "#FF4654"
_EMOJI = {
    "🎮": "1f3ae.png",
    "🏆": "1f3c6.png",
    "⭐": "2b50.png",
    "🥇": "1f947.png",
    "🥈": "1f948.png",
    "🥉": "1f949.png",
    "💬": "1f4ac.png",
    "👥": "1f465.png",
    "🎙": "1f399.png",
}
_EMOJI_PATTERN = re.compile("([" + "".join(_EMOJI) + "])")


@dataclass(frozen=True, slots=True)
class QuoteCard:
    """Текст цитаты и публичная подпись; упоминания заранее раскрывает вызывающий код."""

    text: str
    display_name: str
    username: str
    created_at: datetime
    channel_name: str


@lru_cache(maxsize=48)
def _font(size: int, weight: str = "Medium") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_ASSETS / "fonts" / f"Montserrat-{weight}.ttf"), size)


@lru_cache(maxsize=2048)
def _has_glyph(char: str) -> bool:
    font = _font(32, "SemiBold")
    mask = font.getmask(char)
    missing = font.getmask("\U0010ffff")
    return mask.size != missing.size or bytes(mask) != bytes(missing)


def _variation(char: str) -> bool:
    return 0xFE00 <= ord(char) <= 0xFE0F or 0xE0100 <= ord(char) <= 0xE01EF


def _extension(char: str) -> bool:
    return (
        _variation(char)
        or unicodedata.category(char) in ("Mn", "Mc", "Me")
        or 0x1F3FB <= ord(char) <= 0x1F3FF
        or 0xE0020 <= ord(char) <= 0xE007F
    )


def _clusters(text: str) -> list[str]:
    """Сохраняет целиком emoji с ZWJ, оттенком кожи, флагами и keycap."""
    result: list[str] = []
    index = 0
    while index < len(text):
        start = index
        index += 1
        if (
            0x1F1E6 <= ord(text[start]) <= 0x1F1FF
            and index < len(text)
            and 0x1F1E6 <= ord(text[index]) <= 0x1F1FF
        ):
            index += 1
        while index < len(text):
            if _extension(text[index]):
                index += 1
            elif text[index] == "\u200d" and index + 1 < len(text):
                index += 2
            else:
                break
        result.append(text[start:index])
    return result


def _fallback(cluster: str) -> str:
    if len(cluster) == 2 and all(0x1F1E6 <= ord(char) <= 0x1F1FF for char in cluster):
        country = "".join(chr(ord(char) - 0x1F1E6 + ord("A")) for char in cluster)
        return f"[flag {country}]"
    parts: list[str] = []
    for char in cluster:
        if _variation(char) or char == "\u200d":
            continue
        name = unicodedata.name(char, "")
        if ord(char) >= 0x1F000 or 0x2300 <= ord(char) <= 0x27FF:
            name = name.lower().replace(" sign", "").replace("emoji modifier fitzpatrick ", "")
            parts.append(name or f"U+{ord(char):04X}")
        elif len(cluster) > 1 and name:
            parts.append(name.lower())
        else:
            parts.append(f"U+{ord(char):04X}")
    return "[" + " / ".join(parts or [f"U+{ord(cluster[0]):04X}"]) + "]"


def _display_text(text: str) -> str:
    """Делает отсутствующие glyph и управляющие символы видимыми, без tofu."""
    result: list[str] = []
    for cluster in _clusters(text.replace("\r\n", "\n").replace("\r", "\n")):
        if len(cluster) > 32:
            raise ValueError("Слишком сложная последовательность символов для читаемой карточки.")
        plain = "".join(char for char in cluster if not _variation(char))
        if plain == "\n":
            result.append("\n")
        elif plain == "\t":
            result.append("    ")
        elif plain in _EMOJI:
            result.append(plain)
        elif plain and all(
            not unicodedata.category(char).startswith("C") and _has_glyph(char) for char in plain
        ):
            result.append(plain)
        else:
            result.append(_fallback(cluster))
    return "".join(result)


def _advance(text: str, font: ImageFont.FreeTypeFont) -> float:
    return sum(
        font.size * 1.12 if part in _EMOJI else font.getlength(part)
        for part in _EMOJI_PATTERN.split(text)
        if part
    )


def _wrap(text: str, font: ImageFont.FreeTypeFont, available: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for token in re.findall(r"\S+|\s+", paragraph):
            if current and _advance(current + token, font) > available and not token.isspace():
                lines.append(current.rstrip())
                current = ""
            for cluster in _clusters(token):
                if current and _advance(current + cluster, font) > available:
                    lines.append(current.rstrip())
                    current = ""
                if current or not cluster.isspace():
                    current += cluster
        lines.append(current.rstrip())
    return lines


def _line(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: str = _FG,
) -> None:
    draw = ImageDraw.Draw(image)
    x, y = float(xy[0]), xy[1]
    for part in _EMOJI_PATTERN.split(text):
        if not part:
            continue
        if part in _EMOJI:
            with Image.open(_ASSETS / "emoji" / _EMOJI[part]) as source:
                icon = source.convert("RGBA").resize(
                    (font.size, font.size), Image.Resampling.LANCZOS
                )
            image.paste(icon, (round(x), y + 2), icon)
            x += font.size * 1.12
        else:
            draw.text((x, y + font.size), part, font=font, fill=fill, anchor="ls")
            x += font.getlength(part)


def _decode_avatar(raw: bytes | None) -> Image.Image | None:
    if not raw or len(raw) > _MAX_AVATAR_BYTES:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.width * source.height > _MAX_AVATAR_PIXELS:
                    return None
                source.seek(0)
                rgba = ImageOps.exif_transpose(source).convert("RGBA")
                background = Image.new("RGB", rgba.size, _BG)
                background.paste(rgba, mask=rgba.getchannel("A"))
                return background
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return None


def _initials(card: QuoteCard, size: tuple[int, int]) -> Image.Image:
    seed = hashlib.blake2b(card.username.encode("utf-8", errors="replace"), digest_size=1).digest()[
        0
    ]
    shade = 54 + seed % 36
    image = Image.new("RGB", size, (shade, shade, shade))
    letters = [word[0].upper() for word in card.display_name.split() if word]
    initials = "".join(char if _has_glyph(char) else "?" for char in letters[:2]) or "?"
    font = _font(144, "Bold")
    ImageDraw.Draw(image).text(
        (round(size[0] * 0.32), size[1] // 2),
        initials,
        font=font,
        fill="#DCD8D8",
        anchor="mm",
    )
    return image


def _background(card: QuoteCard, avatar: bytes | None, height: int, text_x: int) -> Image.Image:
    portrait_width = 535 if text_x == 420 else 666
    source = _decode_avatar(avatar)
    portrait = (
        ImageOps.fit(source, (portrait_width, height), centering=(0.42, 0.45))
        if source is not None
        else _initials(card, (portrait_width, height))
    )
    portrait = ImageOps.colorize(ImageOps.grayscale(portrait), "#241018", "#ECE7E5")
    fade = Image.new("L", (portrait_width, 1))
    fade_start = portrait_width * 0.30
    fade_end = text_x - 16
    row: list[int] = []
    for x in range(portrait_width):
        progress = max(0.0, min(1.0, (x - fade_start) / (fade_end - fade_start)))
        smooth = progress * progress * (3 - 2 * progress)
        row.append(round(255 * (1 - smooth)))
    fade.putdata(row)
    image = Image.new("RGB", (_WIDTH, height), _BG)
    image.paste(portrait, (0, 0), fade.resize((portrait_width, height)))
    shade = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(shade)
    for y in range(height - 140, height):
        opacity = round(140 * ((y - height + 140) / 140) ** 1.5)
        draw.line((0, y, _WIDTH, y), fill=(16, 16, 20, opacity))
    return Image.alpha_composite(image.convert("RGBA"), shade).convert("RGB")


def _metadata(text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    text = _display_text(" ".join(text.split()))
    if _advance(text, font) <= width:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _advance(text[:middle] + "…", font) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…"


def render_quote_card(
    card: QuoteCard, avatar: bytes | None = None, *, max_bytes: int = 262144
) -> bytes:
    """Рисует карточку PD Room, сохраняя весь текст цитаты в пределах читаемого макета.

    Args:
        card: Цитата длиной до 1000 символов и публичные сведения об авторе.
        avatar: Исходный аватар до 2 МиБ; неподходящий заменяется инициалами.
        max_bytes: Максимальный размер WebP, не более 1 МиБ.

    Returns:
        Содержимое WebP шириной 1200 px и высотой от 640 до 1200 px.

    Raises:
        ValueError: Пустой/слишком длинный текст, неверные параметры или текст,
            который нельзя вместить без чрезмерного уменьшения шрифта. Отсутствующие
            emoji/glyph отображаются явными текстовыми токенами, цитата не обрезается.
    """
    text = card.text.strip()
    if not text or len(text) > 1000:
        raise ValueError("Для карточки нужен текст от 1 до 1000 символов.")
    if type(max_bytes) is not int or not 0 < max_bytes <= 1024 * 1024:
        raise ValueError("Лимит WebP должен быть от 1 байта до 1 МиБ.")
    if card.created_at.utcoffset() is None:
        raise ValueError("Для даты цитаты нужен часовой пояс.")
    if any(len(value) > 200 for value in (card.display_name, card.username, card.channel_name)):
        raise ValueError("Подпись цитаты слишком длинная.")
    text = _display_text(text)
    long = len(text) > 180 or text.count("\n") > 5
    text_x = 420 if long else 592
    available = _WIDTH - text_x - 76
    preferred = 104 if len(text) <= 40 else 64 if len(text) <= 140 else 44 if long else 48
    for size in range(preferred, _MIN_FONT_SIZE - 1, -2):
        body_font = _font(size, "SemiBold")
        lines = _wrap(text, body_font, available)
        line_height = math.ceil(size * 1.35)
        body_height = sum(line_height if line else round(line_height * 0.55) for line in lines)
        height = max(640, body_height + 300)
        if height <= _MAX_HEIGHT:
            break
    else:
        raise ValueError(
            "Текст не помещается в читаемую карточку. Выбери более короткое сообщение."
        )

    image = _background(card, avatar, height, text_x)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 6, height), fill=_RED)
    date = card.created_at.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y")
    heading = _metadata(f"{date}  /  #{card.channel_name}", _font(16), available)
    _line(
        image,
        (_WIDTH - 42 - round(_advance(heading, _font(16))), 28),
        heading,
        _font(16),
        fill="#82808B",
    )
    author_font = _font(25, "SemiBold")
    author = _metadata(card.display_name or "Автор", author_font, available - 38)
    username = _metadata("@" + card.username.lstrip("@"), _font(18), available - 38)
    if len(text) <= 40:
        block_width = max(
            38 + _advance(author, author_font),
            38 + _advance(username, _font(18)),
            *(_advance(line, body_font) for line in lines),
        )
        text_x += max(0, round((available - block_width) / 2))
    start = (height - body_height - 100) // 2
    draw.text((text_x - 4, start - 70), "“", font=_font(86, "Bold"), fill=_RED, anchor="lt")
    y = start
    for line in lines:
        if line:
            _line(image, (text_x, y), line, body_font)
            y += line_height
        else:
            y += round(line_height * 0.55)
    y += 24
    draw.line((text_x, y + 14, text_x + 24, y + 14), fill=_RED, width=3)
    _line(image, (text_x + 38, y - 4), author, author_font)
    _line(image, (text_x + 38, y + 36), username, _font(18), fill=_MUTED)
    draw.text((_WIDTH - 42, height - 37), "PD ROOM", font=_font(17, "Bold"), fill=_RED, anchor="rs")

    for quality in (92, 84, 76, 68):
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        encoded = output.getvalue()
        if len(encoded) <= max_bytes:
            return encoded
    raise ValueError("Карточка не помещается в заданный размер файла без потери читаемости.")
