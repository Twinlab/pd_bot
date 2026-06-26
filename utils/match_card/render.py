"""Рендер карточек последнего матча (CS2 и Dota 2) средствами Pillow.

Карточка — квадрат 1080×1080: фоновый арт (сплеш карты / рендер героя) с
затемнением, сверху «результат во главе» (VICTORY/DEFEAT настоящим цветом + счёт),
крупный вердикт-комментарий, число-якорь (Rating/KDA), сетка статов и круглый аватар.
Для CS — плитки W/L по последним матчам; для Dota — ряд иконок предметов.
Лейблы английские (универсально); вердикт-комментарий передаётся как есть.

Шрифт — забандленный Montserrat из ``utils/wrapped/assets/fonts`` (кириллица). Семья к
wrapped-постерам (:mod:`utils.wrapped.render`), но здесь чистый Pillow ради
попиксельной вёрстки. Функции синхронные и блокирующие — звать через ``asyncio.to_thread``.
"""

import logging
from io import BytesIO
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont

from .types import CsCardData, DotaCardData, ItemImage

logger = logging.getLogger("bot.utils.match_card.render")

W = H = 1080
M = 64

BG = (14, 17, 22)
AV_BG = (38, 44, 56)
TEXT = (248, 250, 252)
MUTED = (148, 163, 184)
WIN = (74, 222, 128)
LOSS = (248, 113, 113)
AMBER = (245, 158, 11)

_FONTS_DIR = Path(__file__).resolve().parents[1] / "wrapped" / "assets" / "fonts"
_FONT_FILES = {
    "bold": "Montserrat-Bold.ttf",
    "semibold": "Montserrat-SemiBold.ttf",
    "medium": "Montserrat-Medium.ttf",
    "regular": "Montserrat-Regular.ttf",
}
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

_SEP = "  ·  "


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """Возвращает (кэшированный) Montserrat нужного начертания и размера."""
    key = (weight, size)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    path = _FONTS_DIR / _FONT_FILES[weight]
    try:
        font = ImageFont.truetype(str(path), size)
    except OSError:
        font = cast(ImageFont.FreeTypeFont, ImageFont.load_default(size))
    _font_cache[key] = font
    return font


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """Масштабирует с сохранением пропорций и центр-кропом под бокс ``w×h`` (как CSS cover)."""
    if im.width == 0 or im.height == 0:
        return im.resize((w, h))
    src, dst = im.width / im.height, w / h
    if src > dst:
        new_w, new_h = round(h * src), h
    else:
        new_w, new_h = w, round(w / src)
    im = im.resize((max(1, new_w), max(1, new_h)), Image.Resampling.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def _circle(data: bytes, size: int) -> Image.Image | None:
    """Круглый RGBA-кроп картинки диаметром ``size`` (None при битых байтах)."""
    try:
        im = Image.open(BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    im = _cover(im, size, size)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    im.putalpha(mask)
    return im


def _fallback_avatar(label: str, size: int) -> Image.Image:
    """Заглушка-аватар: муарный диск с первой буквой ника (когда картинки нет)."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(*AV_BG, 255))
    letter = (label.strip()[:1] or "?").upper()
    draw.text(
        (size / 2, size / 2 - 2),
        letter,
        font=_font("bold", int(size * 0.46)),
        fill=(*TEXT, 255),
        anchor="mm",
    )
    return im


def _avatar(data: bytes | None, label: str, size: int) -> Image.Image:
    """Круглый аватар из байтов, либо буквенная заглушка — но всегда что-то рисуем."""
    if data:
        circle = _circle(data, size)
        if circle is not None:
            return circle
    return _fallback_avatar(label, size)


def _vgrad(a_top: int, a_bot: int) -> Image.Image:
    """Вертикальный чёрный градиент с альфой от ``a_top`` сверху до ``a_bot`` снизу."""
    column = Image.new("L", (1, H))
    for y in range(H):
        column.putpixel((0, y), int(a_top + (a_bot - a_top) * y / (H - 1)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer.putalpha(column.resize((W, H)))
    return layer


def _background(art: bytes | None, accent: tuple[int, int, int]) -> Image.Image:
    """Собирает фон: арт «cover» → затемнение → нижне-тяжёлый градиент → тон результата."""
    base = Image.new("RGBA", (W, H), (*BG, 255))
    if art:
        try:
            art_im = Image.open(BytesIO(art)).convert("RGBA")
            base.alpha_composite(_cover(art_im, W, H))
        except Exception as e:
            logger.debug("Фоновый арт не отрисован: %s", e)
    base.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 110)))
    base.alpha_composite(_vgrad(45, 220))
    base.alpha_composite(Image.new("RGBA", (W, H), (*accent, 22)))
    return base


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    anchor: str = "la",
) -> None:
    draw.text(xy, text, font=font, fill=(*fill, 255), anchor=anchor)


def _fit_font(
    draw: ImageDraw.ImageDraw, text: str, weight: str, max_size: int, min_size: int, max_width: int
) -> ImageFont.FreeTypeFont:
    """Подбирает максимальный размер начертания, при котором ``text`` влезает в ``max_width``."""
    size = max_size
    while size > min_size:
        font = _font(weight, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(weight, min_size)


def _rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _draw_header(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    result_line: str,
    verdict: str,
    identity: str,
    accent: tuple[int, int, int],
    portrait: Image.Image,
) -> None:
    """Шапка: результат+счёт, крупный вердикт, строка идентичности, круглый аватар справа."""
    size = portrait.width
    img.alpha_composite(portrait, (W - M - size, 52))
    draw.ellipse((W - M - size, 52, W - M, 52 + size), outline=(255, 255, 255, 70), width=3)

    verdict_width = W - 2 * M - size - 24
    _text(draw, (M, 58), result_line, _font("semibold", 38), accent)
    verdict_font = _fit_font(draw, verdict, "bold", 64, 34, verdict_width)
    _text(draw, (M, 104), verdict, verdict_font, TEXT)
    _text(draw, (M, 182), identity, _font("medium", 28), MUTED)


def _stat_cell(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    value: str,
    value_color: tuple[int, int, int] = TEXT,
) -> None:
    """Ячейка «подпись сверху мелко, значение снизу крупно»."""
    _text(draw, (x, y), label, _font("semibold", 24), MUTED)
    _text(draw, (x, y + 30), value, _font("bold", 40), value_color)


def _recent_tiles(
    draw: ImageDraw.ImageDraw, x: int, y: int, results: list[bool], max_n: int = 10
) -> None:
    """Ряд плиток W/L (свежие — слева): зелёная победа, красное поражение."""
    tile, gap = 34, 8
    for i, win in enumerate(results[:max_n]):
        tx = x + i * (tile + gap)
        _rounded(draw, (tx, y, tx + tile, y + tile), 8, (*(WIN if win else LOSS), 255))


def _item_slot(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    item: ItemImage | None,
    ring: bool = False,
) -> None:
    """Слот предмета: подложка, иконка «cover» со скруглением, опциональное кольцо нейтралки."""
    _rounded(draw, (x, y, x + w, y + h), 10, (255, 255, 255, 18))
    if item is not None and item.image:
        try:
            icon = _cover(Image.open(BytesIO(item.image)).convert("RGBA"), w, h)
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=10, fill=255)
            icon.putalpha(mask)
            img.alpha_composite(icon, (x, y))
        except Exception as e:
            logger.debug("Иконка предмета не отрисована: %s", e)
    if ring:
        draw.rounded_rectangle(
            (x, y, x + w - 1, y + h - 1), radius=10, outline=(*AMBER, 255), width=3
        )


def _draw_anchor(
    draw: ImageDraw.ImageDraw, label: str, value: str, color: tuple[int, int, int]
) -> None:
    _text(draw, (M, 300), label, _font("semibold", 26), MUTED)
    _text(draw, (M, 332), value, _font("bold", 104), color)


def _draw_context(draw: ImageDraw.ImageDraw, text: str) -> None:
    draw.line((M, 230, W - M, 230), fill=(255, 255, 255, 40), width=2)
    _text(draw, (M, 250), text, _font("medium", 27), MUTED)


def _draw_footer(draw: ImageDraw.ImageDraw, right: str) -> None:
    draw.line((M, 1000, W - M, 1000), fill=(255, 255, 255, 28), width=2)
    _text(draw, (M, 1018), "PD Bot", _font("semibold", 24), MUTED)
    _text(draw, (W - M, 1018), right, _font("regular", 24), MUTED, anchor="ra")


def _finish(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def render_cs_card(data: CsCardData) -> bytes:
    """Рендерит карточку последнего матча CS2 в PNG-байты.

    Args:
        data: Готовые к отрисовке значения и байты картинок (см. :class:`CsCardData`).

    Returns:
        PNG-байты карточки 1080×1080.
    """
    accent = WIN if data.is_victory else LOSS
    img = _background(data.map_bg, accent)
    draw = ImageDraw.Draw(img)

    result_line = (
        f"{'VICTORY' if data.is_victory else 'DEFEAT'}  ·  {data.player_score} : {data.opp_score}"
    )
    identity = _SEP.join([data.nickname, f"LVL {data.level}", f"{data.elo} ELO"])
    _draw_header(
        img,
        draw,
        result_line=result_line,
        verdict=data.verdict,
        identity=identity,
        accent=accent,
        portrait=_avatar(data.avatar, data.nickname, 168),
    )

    context = [data.date_str, data.duration_str]
    if data.avg_lobby_lvl is not None:
        context.append(f"avg lobby {data.avg_lobby_lvl}")
    _draw_context(draw, _SEP.join(context))

    _draw_anchor(draw, "RATING", data.rating_str, WIN if data.rating_is_good else TEXT)

    # Хедлайн-ряд: справа от рейтинга — форма по последним матчам плитками W/L.
    recent_x = 600
    _text(draw, (recent_x, 300), "RECENT", _font("semibold", 26), MUTED)
    _recent_tiles(draw, recent_x, 342, data.recent_results)
    _text(
        draw,
        (recent_x, 392),
        f"{data.recent_wins}–{data.recent_losses} (W-L)",
        _font("medium", 26),
        MUTED,
    )

    col1, col2, col3 = M, 380, 696
    row1, row2, row3 = 470, 568, 666
    _stat_cell(draw, col1, row1, "K/D/A", data.kda_str)
    _stat_cell(draw, col2, row1, "K/D", data.kd_str)
    _stat_cell(draw, col3, row1, "ADR", data.adr_str)
    _stat_cell(draw, col1, row2, "HS", f"{data.hs_percent}%")
    _stat_cell(draw, col2, row2, "MVP", data.mvp_str)
    _stat_cell(draw, col3, row2, "K/R", data.kr_str)
    _stat_cell(draw, col1, row3, "ENTRY", data.entry_str)
    _stat_cell(draw, col2, row3, "CLUTCH", data.clutch_str)
    _stat_cell(draw, col3, row3, "UTIL DMG", data.util_str)

    _draw_footer(draw, "CS2")
    return _finish(img)


def render_dota_card(data: DotaCardData) -> bytes:
    """Рендерит карточку последнего матча Dota 2 в PNG-байты.

    Args:
        data: Готовые к отрисовке значения и байты картинок (см. :class:`DotaCardData`).

    Returns:
        PNG-байты карточки 1080×1080.
    """
    accent = WIN if data.is_victory else LOSS
    img = _background(data.hero_bg, accent)
    draw = ImageDraw.Draw(img)

    result_line = f"{'VICTORY' if data.is_victory else 'DEFEAT'}  ·  {data.game_mode}"
    identity = _SEP.join([data.player_name, data.role])
    _draw_header(
        img,
        draw,
        result_line=result_line,
        verdict=data.verdict,
        identity=identity,
        accent=accent,
        portrait=_avatar(data.avatar, data.player_name, 168),
    )

    _draw_context(draw, _SEP.join([data.date_str, data.duration_str, f"avg {data.rank}"]))

    _draw_anchor(draw, "KDA", data.kda_value_str, TEXT)

    grid_x1, grid_x2, row1, row2 = 540, 800, 324, 432
    _stat_cell(draw, grid_x1, row1, "K/D/A", data.kda_str)
    _stat_cell(draw, grid_x2, row1, "HERO DMG", data.hero_damage)
    _stat_cell(draw, grid_x1, row2, "NETWORTH", data.networth)
    _stat_cell(draw, grid_x2, row2, "GPM/XPM", f"{data.gpm}/{data.xpm}")

    _text(draw, (M, 596), "ITEMS", _font("semibold", 24), MUTED)
    slot_w, slot_h, gap, items_y = 96, 72, 14, 632
    for i in range(6):
        item = data.items[i] if i < len(data.items) else None
        _item_slot(img, draw, M + i * (slot_w + gap), items_y, slot_w, slot_h, item)
    if data.neutral is not None:
        nx = M + 6 * (slot_w + gap) + 28
        _item_slot(img, draw, nx, items_y, slot_w, slot_h, data.neutral, ring=True)

    _text(draw, (M, 770), "W-L", _font("semibold", 26), MUTED)
    wl = _SEP.join([f"day {data.daily_wl}", f"week {data.weekly_wl}"])
    _text(draw, (M, 802), wl, _font("bold", 38), TEXT)

    _draw_footer(draw, "Dota 2")
    return _finish(img)
