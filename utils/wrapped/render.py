"""Рендер wrapped-карточек средствами matplotlib (Agg, без GUI).

Шрифт — забандленный Montserrat (`assets/fonts/`), который поддерживает кириллицу
и даёт «постерный» вид; при отсутствии файлов используется встроенный DejaVu Sans.
Эмодзи рисуются цветными Twemoji-PNG (`assets/emoji/`) как картинки — поэтому
«тофу»-квадратов нет, а иконки/номинации выглядят празднично.

Функции синхронные и блокирующие — вызывать через ``asyncio.to_thread``.
"""

from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import Ellipse, FancyBboxPatch  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from .builder import PersonalWrapped, ServerWrapped

_FIG_W = 7.2
_FIG_H = 9.0
# Ось 0..100 по обеим сторонам, но фигура не квадратная — чтобы круг/иконка не
# превращались в эллипс, высоту в data-единицах берём как ширину * (_FIG_W/_FIG_H).
_AVATAR_AR = _FIG_W / _FIG_H

_BG_TOP = (0.10, 0.12, 0.20)
_BG_BOTTOM = (0.02, 0.03, 0.06)
_ACCENT = "#1DB954"
_ACCENT2 = "#38BDF8"
_AMBER = "#F59E0B"
_PINK = "#F472B6"
_TEXT = "#F8FAFC"
_MUTED = "#94A3B8"
_CARD = (1.0, 1.0, 1.0, 0.06)

_ASSETS_DIR = Path(__file__).parent / "assets"
_FONTS_DIR = _ASSETS_DIR / "fonts"
_EMOJI_DIR = _ASSETS_DIR / "emoji"

ICON_MSG = "💬"
ICON_VOICE = "🎙️"
ICON_GAME = "🎮"
ICON_STAR = "⭐"
ICON_USERS = "👥"
ICON_TROPHY = "🏆"
_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# Литеральный эмодзи -> кодпоинт Twemoji-файла (без variation selector).
_EMOJI_CODES = {
    ICON_MSG: "1f4ac",
    ICON_VOICE: "1f399",
    "🎙": "1f399",
    ICON_GAME: "1f3ae",
    ICON_STAR: "2b50",
    ICON_USERS: "1f465",
    ICON_TROPHY: "1f3c6",
    _MEDALS[1]: "1f947",
    _MEDALS[2]: "1f948",
    _MEDALS[3]: "1f949",
}

Avatars = dict[int, bytes] | None


def _load_font(filename: str) -> FontProperties:
    """Регистрирует TTF и возвращает FontProperties (фолбэк — встроенный DejaVu)."""
    path = _FONTS_DIR / filename
    if path.exists():
        try:
            font_manager.fontManager.addfont(str(path))
            return FontProperties(fname=str(path))
        except Exception:
            pass
    return FontProperties()


_FONT_BOLD = _load_font("Montserrat-Bold.ttf")
_FONT_SEMIBOLD = _load_font("Montserrat-SemiBold.ttf")
_FONT_MEDIUM = _load_font("Montserrat-Medium.ttf")
_FONT_REGULAR = _load_font("Montserrat-Regular.ttf")

_icon_cache: dict[str, np.ndarray | None] = {}


def _icon_array(emoji: str) -> np.ndarray | None:
    """Возвращает RGBA-массив Twemoji-иконки (None, если файла нет)."""
    if emoji in _icon_cache:
        return _icon_cache[emoji]
    code = _EMOJI_CODES.get(emoji)
    arr: np.ndarray | None = None
    if code is not None:
        path = _EMOJI_DIR / f"{code}.png"
        if path.exists():
            try:
                arr = np.asarray(Image.open(path).convert("RGBA"))
            except Exception:
                arr = None
    _icon_cache[emoji] = arr
    return arr


def _hex_rgb(color: str) -> tuple[float, float, float]:
    h = color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _fmt_hm(seconds: int) -> str:
    if seconds <= 0:
        return "0м"
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours > 0:
        return f"{hours}ч {minutes}м" if minutes else f"{hours}ч"
    return f"{minutes}м"


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _text(
    ax: plt.Axes,
    x: float,
    y: float,
    s: str,
    *,
    size: float,
    color: str,
    font: FontProperties,
    ha: str = "left",
    va: str = "baseline",
    zorder: float = 2,
    alpha: float = 1.0,
) -> None:
    ax.text(
        x,
        y,
        s,
        color=color,
        fontsize=size,
        fontproperties=font,
        ha=ha,
        va=va,
        zorder=zorder,
        alpha=alpha,
    )


def _draw_icon(
    ax: plt.Axes,
    emoji: str,
    *,
    x: float,
    y: float,
    w: float,
    alpha: float = 1.0,
    zorder: float = 3,
) -> bool:
    """Рисует Twemoji-иконку с левым-нижним углом в (x, y) и шириной ``w`` (data-единицы).

    Returns:
        True, если иконка отрисована; False — если файла нет (вызывающий рисует текст).
    """
    arr = _icon_array(emoji)
    if arr is None:
        return False
    if alpha != 1.0:
        arr = arr.copy()
        arr[..., 3] = (arr[..., 3].astype(float) * alpha).astype(arr.dtype)
    h = w * _AVATAR_AR
    ax.imshow(
        arr,
        extent=(x, x + w, y, y + h),
        origin="upper",
        zorder=zorder,
        aspect="auto",
        interpolation="antialiased",
    )
    return True


def _circular_avatar_array(img_bytes: bytes, size: int = 160) -> np.ndarray | None:
    """Готовит круглый RGBA-массив аватара (None при битых байтах)."""
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA").resize((size, size))
    except Exception:
        return None
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    rgba = np.dstack([np.asarray(im)[..., :3], np.asarray(mask)])
    return rgba


def _draw_avatar(ax: plt.Axes, img_bytes: bytes, *, x: float, y: float, w: float) -> bool:
    """Рисует круглый аватар c левым-нижним углом в (x, y) и шириной ``w`` (data-единицы).

    Returns:
        True, если аватар отрисован; False — если байты битые (нарисуем заглушку выше).
    """
    arr = _circular_avatar_array(img_bytes)
    if arr is None:
        return False
    h = w * _AVATAR_AR
    ax.imshow(
        arr,
        extent=(x, x + w, y, y + h),
        origin="upper",
        zorder=4,
        aspect="auto",
        interpolation="antialiased",
    )
    # Кольцо рисуем эллипсом (width=w, height=h): ось не квадратная, поэтому
    # Circle с радиусом в data-единицах выглядел бы овалом.
    ax.add_patch(
        Ellipse(
            (x + w / 2, y + h / 2),
            width=w,
            height=h,
            fill=False,
            edgecolor=(1, 1, 1, 0.25),
            linewidth=1.2,
            zorder=5,
        )
    )
    return True


def _radial_glow(
    ax: plt.Axes, cx: float, cy: float, radius: float, color: str, max_alpha: float
) -> None:
    """Мягкое радиальное «свечение» цветом ``color`` поверх фона (Spotify-вайб)."""
    n = 200
    grid = np.linspace(0, 100, n)
    gx, gy = np.meshgrid(grid, grid)
    # Делим вертикаль на AR, чтобы свечение было круглым физически, а не сплющенным.
    dist = np.sqrt((gx - cx) ** 2 + ((gy - cy) / _AVATAR_AR) ** 2)
    alpha = np.clip(1 - dist / radius, 0, 1) ** 2 * max_alpha
    r, g, b = _hex_rgb(color)
    img = np.zeros((n, n, 4))
    img[..., 0] = r
    img[..., 1] = g
    img[..., 2] = b
    img[..., 3] = alpha
    ax.imshow(img, extent=(0, 100, 0, 100), origin="lower", aspect="auto", zorder=0.5)


def _new_canvas() -> tuple[plt.Figure, plt.Axes]:
    """Создаёт постер 1080x1350 с тёмным градиентом и акцент-свечениями."""
    fig = plt.figure(figsize=(_FIG_W, _FIG_H), dpi=150)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    rgb = np.zeros((256, 1, 3))
    for i in range(3):
        rgb[:, 0, i] = np.linspace(_BG_BOTTOM[i], _BG_TOP[i], 256)
    ax.imshow(rgb, extent=(0, 100, 0, 100), aspect="auto", origin="lower", zorder=0)

    _radial_glow(ax, cx=12, cy=92, radius=55, color=_ACCENT, max_alpha=0.20)
    _radial_glow(ax, cx=96, cy=18, radius=60, color=_ACCENT2, max_alpha=0.16)
    return fig, ax


def _card(ax: plt.Axes, x: float, y: float, w: float, h: float) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.4,rounding_size=2.2",
            linewidth=0,
            facecolor=_CARD,
            zorder=1,
        )
    )


def _bar_rows(
    ax: plt.Axes,
    title: str,
    rows: list[tuple[str, int, str]],
    *,
    x: float,
    y_top: float,
    width: float,
    color: str,
    emoji: str | None = None,
) -> float:
    """Рисует блок «заголовок (+иконка) + строки с горизонтальными барами».

    Args:
        rows: список (имя, числовое_значение_для_бара, текст_значения).

    Returns:
        Y-координату низа блока.
    """
    title_x = x
    # Иконку центрируем по визуальной середине строки заголовка (va="top" → центр
    # текста ≈ y_top - 1.1), иначе она «проседает» относительно текста.
    icon_w = 3.4
    if emoji is not None and _draw_icon(
        ax, emoji, x=x, y=y_top - 1.1 - icon_w * _AVATAR_AR / 2, w=icon_w
    ):
        title_x = x + 4.6
    _text(ax, title_x, y_top, title, size=15, color=_TEXT, font=_FONT_BOLD, va="top")

    row_h = 4.0
    gap = 0.9
    y = y_top - 5.0
    max_val = max((v for _, v, _ in rows), default=1) or 1
    for i, (name, value, label) in enumerate(rows, 1):
        bar_w = max(2.0, width * (value / max_val))
        # Подложка-трек на всю ширину для аккуратного «графика».
        ax.add_patch(
            FancyBboxPatch(
                (x, y - row_h),
                width,
                row_h,
                boxstyle="round,pad=0,rounding_size=1.2",
                linewidth=0,
                facecolor=(1, 1, 1, 0.05),
                zorder=1,
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (x, y - row_h),
                bar_w,
                row_h,
                boxstyle="round,pad=0,rounding_size=1.2",
                linewidth=0,
                facecolor=color,
                alpha=0.32,
                zorder=1,
            )
        )
        _text(
            ax,
            x + 1.4,
            y - row_h / 2,
            f"{i}. {_truncate(name, 20)}",
            size=12,
            color=_TEXT,
            font=_FONT_MEDIUM,
            va="center",
        )
        _text(
            ax,
            x + width - 1.4,
            y - row_h / 2,
            label,
            size=12,
            color=color,
            font=_FONT_BOLD,
            va="center",
            ha="right",
        )
        y -= row_h + gap
    return y


def _stat_block(
    ax: plt.Axes, cx: float, cy: float, *, emoji: str, value: str, label: str, color: str
) -> None:
    """Мини-блок статистики: иконка сверху, крупное число, подпись (центр в ``cx``).

    Три уровня — иконка / число / подпись — расставлены с равными промежутками
    относительно центра карточки ``cy``, чтобы блок выглядел сбалансированным.
    """
    icon_w = 4.2
    icon_h = icon_w * _AVATAR_AR
    _draw_icon(ax, emoji, x=cx - icon_w / 2, y=(cy + 3.2) - icon_h / 2, w=icon_w)
    _text(ax, cx, cy - 0.4, value, size=22, color=color, font=_FONT_BOLD, ha="center", va="center")
    _text(
        ax, cx, cy - 3.8, label, size=11, color=_MUTED, font=_FONT_REGULAR, ha="center", va="center"
    )


def _footer(ax: plt.Axes, footnote: str) -> None:
    """Тонкий разделитель + сноска слева и акцентный лейбл «wrapped» справа."""
    ax.plot([6, 94], [6.5, 6.5], color=_MUTED, linewidth=0.8, alpha=0.30, zorder=2)
    _text(ax, 6, 3.4, footnote, size=9.5, color=_MUTED, font=_FONT_REGULAR, va="bottom")
    _text(ax, 94, 3.4, "wrapped", size=10, color=_ACCENT, font=_FONT_BOLD, va="bottom", ha="right")


def _save(fig: plt.Figure) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=_BG_BOTTOM)
    plt.close(fig)
    return buf.getvalue()


def render_server_card(
    summary: ServerWrapped, names: Callable[[int], str], avatars: Avatars = None
) -> bytes:
    """Рендерит серверную карточку wrapped в PNG-байты.

    Args:
        summary: Сводка из :func:`utils.wrapped.builder.build_server_wrapped`.
        names: Функция ``user_id -> отображаемое имя``.
        avatars: Опциональные PNG-байты аватаров ``{user_id: bytes}`` для номинаций.
    """
    avatars = avatars or {}
    fig, ax = _new_canvas()

    _text(ax, 6, 95, "ИТОГИ СЕРВЕРА", size=16, color=_ACCENT, font=_FONT_BOLD, va="top")
    _text(ax, 6, 90.5, summary.period_label, size=30, color=_TEXT, font=_FONT_BOLD, va="top")

    _card(ax, 5, 70.5, 90, 13.5)
    cy = 77.0
    _stat_block(
        ax,
        18,
        cy,
        emoji=ICON_MSG,
        value=f"{summary.total_messages}",
        label="сообщений",
        color=_ACCENT,
    )
    _stat_block(
        ax,
        40,
        cy,
        emoji=ICON_VOICE,
        value=_fmt_hm(summary.total_voice_seconds),
        label="в войсе",
        color=_ACCENT2,
    )
    _stat_block(
        ax,
        62,
        cy,
        emoji=ICON_GAME,
        value=_fmt_hm(summary.total_game_seconds),
        label="в играх",
        color=_AMBER,
    )
    _stat_block(
        ax,
        84,
        cy,
        emoji=ICON_USERS,
        value=f"{summary.active_users}",
        label="активных юзеров",
        color=_PINK,
    )

    msg_rows = [(names(nv.user_id), nv.value, f"{nv.value}") for nv in summary.top_messages]
    voice_rows = [(names(nv.user_id), nv.value, _fmt_hm(nv.value)) for nv in summary.top_voice]
    if msg_rows:
        _bar_rows(
            ax,
            "По сообщениям",
            msg_rows,
            x=6,
            y_top=66.5,
            width=42,
            color=_ACCENT,
            emoji=ICON_MSG,
        )
    if voice_rows:
        _bar_rows(
            ax,
            "По войсу",
            voice_rows,
            x=53,
            y_top=66.5,
            width=41,
            color=_ACCENT2,
            emoji=ICON_VOICE,
        )

    # Если данных по сообщениям/войсу ещё нет (первый месяц сбора), подтягиваем
    # игры/номинации вверх и поясняем пустоту, чтобы карточка не выглядела «сломанной».
    if msg_rows or voice_rows:
        section_top = 36.0
    else:
        section_top = 60.0
        _text(
            ax,
            6,
            66.5,
            "Сообщения и войс начали считаться недавно —",
            size=11.5,
            color=_MUTED,
            font=_FONT_REGULAR,
            va="top",
        )
        _text(
            ax,
            6,
            63.0,
            "появятся в следующих сводках.",
            size=11.5,
            color=_MUTED,
            font=_FONT_REGULAR,
            va="top",
        )

    if summary.top_games:
        game_rows = [(g, sec, _fmt_hm(sec)) for g, sec in summary.top_games]
        _bar_rows(
            ax,
            "Игры",
            game_rows,
            x=6,
            y_top=section_top,
            width=42,
            color=_AMBER,
            emoji=ICON_GAME,
        )

    if summary.nominations:
        # Большой полупрозрачный трофей в правом-нижнем углу заполняет пустоту.
        _draw_icon(ax, ICON_TROPHY, x=64, y=9, w=30, alpha=0.045, zorder=0.7)

        nom_title_x = 53.0
        if _draw_icon(ax, ICON_TROPHY, x=53, y=section_top - 1.1 - 3.4 * _AVATAR_AR / 2, w=3.4):
            nom_title_x = 57.6
        _text(
            ax,
            nom_title_x,
            section_top,
            "Топ юзеров",
            size=15,
            color=_TEXT,
            font=_FONT_BOLD,
            va="top",
        )

        y = section_top - 5.0
        for nom in summary.nominations:
            who = names(nom.user_id) if nom.user_id is not None else "—"
            avatar = avatars.get(nom.user_id) if nom.user_id is not None else None
            drew = bool(avatar) and _draw_avatar(ax, avatar, x=53, y=y - 3.6, w=5.0)
            if drew:
                # Угловой бейдж — эмодзи самой номинации (категория), а не медаль:
                # номинации независимы, ранжировать их между собой 🥇🥈🥉 нельзя.
                _draw_icon(ax, nom.emoji, x=51.9, y=y - 0.6, w=2.6, zorder=6)
            else:
                # Без аватара эмодзи номинации идёт крупно вместо кружка.
                _draw_icon(ax, nom.emoji, x=53.3, y=y - 3.4, w=4.8)
            _text(ax, 60.5, y, nom.title, size=11, color=_MUTED, font=_FONT_REGULAR, va="top")
            _text(
                ax,
                60.5,
                y - 2.5,
                f"{_truncate(who, 16)} · {nom.detail}",
                size=12.5,
                color=_TEXT,
                font=_FONT_SEMIBOLD,
                va="top",
            )
            y -= 6.6

    _footer(ax, summary.footnote or "PD Bot")
    return _save(fig)


def render_personal_card(
    personal: PersonalWrapped, name: str, avatar: bytes | None = None
) -> bytes:
    """Рендерит персональную годовую карточку wrapped в PNG-байты.

    Args:
        personal: Сводка из :func:`utils.wrapped.builder.build_personal_wrapped`.
        name: Отображаемое имя пользователя.
        avatar: Опциональные PNG-байты аватара пользователя для шапки.
    """
    fig, ax = _new_canvas()

    name_max = 22
    if avatar and _draw_avatar(ax, avatar, x=77, y=84, w=16):
        name_max = 16

    _text(ax, 6, 95, "ТВОЙ ГОД", size=16, color=_ACCENT, font=_FONT_BOLD, va="top")
    _text(ax, 6, 90.5, _truncate(name, name_max), size=30, color=_TEXT, font=_FONT_BOLD, va="top")
    _text(ax, 6, 84, personal.period_label, size=14, color=_MUTED, font=_FONT_REGULAR, va="top")

    _card(ax, 5, 63, 90, 14)
    cy = 70.0
    _stat_block(
        ax, 18, cy, emoji=ICON_MSG, value=f"{personal.messages}", label="сообщений", color=_ACCENT
    )
    _stat_block(
        ax,
        40,
        cy,
        emoji=ICON_VOICE,
        value=_fmt_hm(personal.voice_seconds),
        label="в войсе",
        color=_ACCENT2,
    )
    _stat_block(
        ax,
        62,
        cy,
        emoji=ICON_GAME,
        value=_fmt_hm(personal.game_seconds),
        label="в играх",
        color=_AMBER,
    )
    _stat_block(
        ax,
        84,
        cy,
        emoji=ICON_STAR,
        value=f"{personal.reactions_received}",
        label="реакций",
        color=_PINK,
    )

    y = 56.0
    if personal.message_rank:
        _text(
            ax,
            6,
            y,
            f"Место по сообщениям: #{personal.message_rank} из {personal.total_users}",
            size=13,
            color=_TEXT,
            font=_FONT_MEDIUM,
            va="top",
        )
        y -= 4.5
    if personal.voice_rank:
        _text(
            ax,
            6,
            y,
            f"Место по войсу: #{personal.voice_rank} из {personal.total_users}",
            size=13,
            color=_TEXT,
            font=_FONT_MEDIUM,
            va="top",
        )
        y -= 4.5
    if personal.reaction_rank:
        _text(
            ax,
            6,
            y,
            f"Место по полученным реакциям: #{personal.reaction_rank} из {personal.reaction_total}",
            size=13,
            color=_TEXT,
            font=_FONT_MEDIUM,
            va="top",
        )
        y -= 4.5
    if personal.favorite_game:
        _text(
            ax,
            6,
            y,
            f"Любимая игра: {_truncate(personal.favorite_game, 26)}",
            size=13,
            color=_TEXT,
            font=_FONT_MEDIUM,
            va="top",
        )
        y -= 4.5

    if personal.top_games:
        _draw_icon(ax, ICON_STAR, x=66, y=9, w=28, alpha=0.05, zorder=0.7)
        game_rows = [(g, sec, _fmt_hm(sec)) for g, sec in personal.top_games]
        _bar_rows(
            ax, "Твои игры", game_rows, x=6, y_top=y - 2, width=60, color=_AMBER, emoji=ICON_GAME
        )

    _footer(ax, personal.footnote or "PD Bot")
    return _save(fig)
