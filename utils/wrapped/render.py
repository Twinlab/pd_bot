"""Рендер wrapped-карточек средствами matplotlib (Agg, без GUI).

Шрифт DejaVu Sans (идёт с matplotlib) поддерживает кириллицу. Эмодзи в картинке
сознательно НЕ используем — DejaVu рисует их «тофу»-квадратами; эмодзи живут только
в тексте сообщений рядом с картинкой.

Функции синхронные и блокирующие — вызывать через ``asyncio.to_thread``.
"""

from collections.abc import Callable
from io import BytesIO

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Ellipse, FancyBboxPatch  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from .builder import PersonalWrapped, ServerWrapped

_FIG_W = 7.2
_FIG_H = 9.0
# Ось 0..100 по обеим сторонам, но фигура не квадратная — чтобы аватар-круг не
# превратился в эллипс, высоту в data-единицах берём как ширину * (_FIG_W/_FIG_H).
_AVATAR_AR = _FIG_W / _FIG_H

_BG_TOP = (0.10, 0.12, 0.20)
_BG_BOTTOM = (0.02, 0.03, 0.06)
_ACCENT = "#1DB954"
_ACCENT2 = "#38BDF8"
_TEXT = "#F8FAFC"
_MUTED = "#94A3B8"
_CARD = (1.0, 1.0, 1.0, 0.06)

Avatars = dict[int, bytes] | None


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
        zorder=3,
        aspect="auto",
        interpolation="antialiased",
    )
    # Кольцо рисуем именно эллипсом (width=w, height=h): ось не квадратная,
    # поэтому Circle с радиусом в data-единицах выглядел бы овалом.
    ax.add_patch(
        Ellipse(
            (x + w / 2, y + h / 2),
            width=w,
            height=h,
            fill=False,
            edgecolor=(1, 1, 1, 0.25),
            linewidth=1.2,
            zorder=4,
        )
    )
    return True


def _new_canvas() -> tuple[plt.Figure, plt.Axes]:
    """Создаёт постер 1080x1350 с тёмным вертикальным градиентом."""
    fig = plt.figure(figsize=(_FIG_W, _FIG_H), dpi=150)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    rgb = np.zeros((256, 1, 3))
    for i in range(3):
        rgb[:, 0, i] = np.linspace(_BG_BOTTOM[i], _BG_TOP[i], 256)
    ax.imshow(rgb, extent=(0, 100, 0, 100), aspect="auto", origin="lower", zorder=0)
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
) -> float:
    """Рисует блок «заголовок + строки с горизонтальными барами».

    Args:
        rows: список (имя, числовое_значение_для_бара, текст_значения).

    Returns:
        Y-координату низа блока.
    """
    ax.text(x, y_top, title, color=_TEXT, fontsize=15, fontweight="bold", va="top")
    row_h = 4.0
    gap = 0.9
    y = y_top - 4.5
    max_val = max((v for _, v, _ in rows), default=1) or 1
    for i, (name, value, label) in enumerate(rows, 1):
        bar_w = max(2.0, width * (value / max_val))
        ax.add_patch(
            FancyBboxPatch(
                (x, y - row_h),
                bar_w,
                row_h,
                boxstyle="round,pad=0,rounding_size=1.2",
                linewidth=0,
                facecolor=color,
                alpha=0.22,
                zorder=1,
            )
        )
        ax.text(
            x + 1.2,
            y - row_h / 2,
            f"{i}. {_truncate(name, 22)}",
            color=_TEXT,
            fontsize=12,
            va="center",
            zorder=2,
        )
        ax.text(
            x + width - 1.2,
            y - row_h / 2,
            label,
            color=color,
            fontsize=12,
            fontweight="bold",
            va="center",
            ha="right",
            zorder=2,
        )
        y -= row_h + gap
    return y


def _stat_block(ax: plt.Axes, x: float, y: float, value: str, label: str, color: str) -> None:
    """Рисует «большое число + подпись», центрируя пару вокруг ``y`` (центр карточки)."""
    ax.text(
        x, y + 2.2, value, color=color, fontsize=26, fontweight="bold", va="center", ha="center"
    )
    ax.text(x, y - 3.0, label, color=_MUTED, fontsize=12, va="center", ha="center")


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

    ax.text(6, 95, "ИТОГИ СЕРВЕРА", color=_ACCENT, fontsize=16, fontweight="bold", va="top")
    ax.text(6, 90.5, summary.period_label, color=_TEXT, fontsize=30, fontweight="bold", va="top")

    _card(ax, 5, 73, 90, 11)
    _stat_block(ax, 18, 78.5, f"{summary.total_messages}", "сообщений", _ACCENT)
    _stat_block(ax, 40, 78.5, _fmt_hm(summary.total_voice_seconds), "в войсе", _ACCENT2)
    _stat_block(ax, 62, 78.5, _fmt_hm(summary.total_game_seconds), "в играх", "#F59E0B")
    _stat_block(ax, 84, 78.5, f"{summary.active_users}", "активных", "#F472B6")

    msg_rows = [(names(nv.user_id), nv.value, f"{nv.value}") for nv in summary.top_messages]
    voice_rows = [(names(nv.user_id), nv.value, _fmt_hm(nv.value)) for nv in summary.top_voice]
    if msg_rows:
        _bar_rows(ax, "Топ по сообщениям", msg_rows, x=6, y_top=70, width=42, color=_ACCENT)
    if voice_rows:
        _bar_rows(ax, "Топ по войсу", voice_rows, x=53, y_top=70, width=41, color=_ACCENT2)

    # Если данных по сообщениям/войсу ещё нет (первый месяц сбора), подтягиваем
    # игры/номинации вверх и поясняем пустоту, чтобы карточка не выглядела «сломанной».
    if msg_rows or voice_rows:
        section_top = 39.0
    else:
        section_top = 60.0
        ax.text(
            6,
            70,
            "Сообщения и войс начали считаться недавно —",
            color=_MUTED,
            fontsize=11.5,
            va="top",
        )
        ax.text(
            6,
            66.5,
            "появятся в следующих сводках.",
            color=_MUTED,
            fontsize=11.5,
            va="top",
        )

    if summary.top_games:
        game_rows = [(g, sec, _fmt_hm(sec)) for g, sec in summary.top_games]
        _bar_rows(ax, "Топ игр", game_rows, x=6, y_top=section_top, width=42, color="#F59E0B")

    if summary.nominations:
        ax.text(53, section_top, "Номинации", color=_TEXT, fontsize=15, fontweight="bold", va="top")
        y = section_top - 4.5
        for nom in summary.nominations:
            who = names(nom.user_id) if nom.user_id is not None else "—"
            avatar = avatars.get(nom.user_id) if nom.user_id is not None else None
            text_x = 53.0
            if avatar and _draw_avatar(ax, avatar, x=53, y=y - 5.6, w=5.0):
                text_x = 60.0
            ax.text(text_x, y, nom.title, color=_MUTED, fontsize=11, va="top")
            ax.text(
                text_x,
                y - 2.6,
                f"{_truncate(who, 16)} · {nom.detail}",
                color=_TEXT,
                fontsize=12.5,
                fontweight="bold",
                va="top",
            )
            y -= 7.2

    footnote = summary.footnote or "PD Bot · Wrapped"
    ax.text(6, 3, footnote, color=_MUTED, fontsize=9.5, va="bottom")

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

    ax.text(6, 95, "ТВОЙ ГОД", color=_ACCENT, fontsize=16, fontweight="bold", va="top")
    ax.text(
        6,
        90.5,
        f"{_truncate(name, name_max)}",
        color=_TEXT,
        fontsize=30,
        fontweight="bold",
        va="top",
    )
    ax.text(6, 84, personal.period_label, color=_MUTED, fontsize=14, va="top")

    _card(ax, 5, 64, 90, 14)
    _stat_block(ax, 18, 71, f"{personal.messages}", "сообщений", _ACCENT)
    _stat_block(ax, 40, 71, _fmt_hm(personal.voice_seconds), "в войсе", _ACCENT2)
    _stat_block(ax, 62, 71, _fmt_hm(personal.game_seconds), "в играх", "#F59E0B")
    _stat_block(ax, 84, 71, f"{personal.reactions_received}", "реакций", "#F472B6")

    y = 56.0
    if personal.message_rank:
        ax.text(
            6,
            y,
            f"Место по сообщениям: #{personal.message_rank} из {personal.total_users}",
            color=_TEXT,
            fontsize=13,
            va="top",
        )
        y -= 4.5
    if personal.voice_rank:
        ax.text(
            6,
            y,
            f"Место по войсу: #{personal.voice_rank} из {personal.total_users}",
            color=_TEXT,
            fontsize=13,
            va="top",
        )
        y -= 4.5
    if personal.reaction_rank:
        ax.text(
            6,
            y,
            f"Место по полученным реакциям: #{personal.reaction_rank} из {personal.reaction_total}",
            color=_TEXT,
            fontsize=13,
            va="top",
        )
        y -= 4.5
    if personal.favorite_game:
        ax.text(
            6,
            y,
            f"Любимая игра: {_truncate(personal.favorite_game, 26)}",
            color=_TEXT,
            fontsize=13,
            va="top",
        )
        y -= 4.5

    if personal.top_games:
        game_rows = [(g, sec, _fmt_hm(sec)) for g, sec in personal.top_games]
        _bar_rows(ax, "Твои игры", game_rows, x=6, y_top=y - 2, width=60, color="#F59E0B")

    footnote = personal.footnote or "PD Bot · Personal Wrapped"
    ax.text(6, 3, footnote, color=_MUTED, fontsize=9.5, va="bottom")

    return _save(fig)
