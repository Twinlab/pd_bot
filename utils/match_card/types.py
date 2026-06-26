"""Дата-классы — вход для рендера карточек матчей.

Хендлеры (`handle_cs_lastmatch`, `handle_lastmatch`) считают всю статистику и
форматируют строки сами, а сюда складывают уже готовые к отрисовке значения плюс
байты картинок (аватар/арт/иконки). Рендер ничего не знает про API и формулы —
только рисует, что дали. Поэтому модуль не импортирует ни discord, ни Pillow.
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class ItemImage:
    """Один предмет Dota для ряда иконок.

    Attributes:
        display_name: Человекочитаемое имя (для пустого слота/отладки).
        image: PNG-байты иконки или None, если картинку не достали.
    """

    display_name: str
    image: bytes | None = None


@dataclass(slots=True)
class CsCardData:
    """Данные для карточки матча CS2.

    ``hs_percent`` нужен числом для подписи; ``recent_results`` — упорядоченная
    (свежие первыми) последовательность исходов для плиток W/L. Остальное — уже
    отформатированные строки. Имя карты тут не нужно: оно и так на фоне.
    """

    verdict: str
    is_victory: bool
    nickname: str
    level: str
    elo: str
    player_score: int
    opp_score: int
    rating_str: str
    rating_is_good: bool
    kda_str: str
    kd_str: str
    adr_str: str
    hs_percent: int
    kr_str: str
    mvp_str: str
    entry_str: str
    clutch_str: str
    util_str: str
    recent_wins: int
    recent_losses: int
    date_str: str
    duration_str: str
    recent_results: list[bool] = field(default_factory=list)
    avg_lobby_lvl: str | None = None
    avatar: bytes | None = None
    map_bg: bytes | None = None


@dataclass(slots=True)
class DotaCardData:
    """Данные для карточки матча Dota 2."""

    verdict: str
    is_victory: bool
    player_name: str
    role: str
    game_mode: str
    rank: str
    kda_value_str: str
    kda_str: str
    hero_damage: str
    networth: str
    gpm: str
    xpm: str
    daily_wl: str
    weekly_wl: str
    date_str: str
    duration_str: str
    items: list[ItemImage] = field(default_factory=list)
    neutral: ItemImage | None = None
    hero_bg: bytes | None = None
    avatar: bytes | None = None
