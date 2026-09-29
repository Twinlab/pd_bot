"""Сбор данных для wrapped-сводок.

Объединяет три источника: статистику сообщений/голоса
(:class:`~utils.user_stats_data_manager.UserStatsDataManager`), игровую активность
(:class:`~utils.activity_data_manager.ActivityDataManager`) и лидерборд реакций
(:class:`~utils.top_reactions_data_manager.TopReactionsDataManager`). На выходе —
структуры, которые рендер превращает в картинку.
"""

from dataclasses import dataclass, field
from typing import Literal

from utils.activity_data_manager import ActivityDataManager
from utils.top_reactions_data_manager import TopReactionsDataManager
from utils.user_stats_data_manager import UserStatsDataManager, UserTotals

WrappedScope = Literal["monthly", "yearly"]

MONTH_NAMES_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


@dataclass(frozen=True, slots=True)
class NamedValue:
    """Пара «пользователь → число» для топов."""

    user_id: int
    value: int


@dataclass(frozen=True, slots=True)
class Nomination:
    """Одна номинация wrapped."""

    emoji: str
    title: str
    user_id: int | None
    detail: str


@dataclass(slots=True)
class ServerWrapped:
    """Серверная сводка за период."""

    period_label: str
    scope: WrappedScope
    total_messages: int
    total_voice_seconds: int
    total_game_seconds: int
    active_users: int
    top_messages: list[NamedValue] = field(default_factory=list)
    top_voice: list[NamedValue] = field(default_factory=list)
    top_games: list[tuple[str, int]] = field(default_factory=list)
    nominations: list[Nomination] = field(default_factory=list)
    footnote: str | None = None
    previous: dict[str, int] = field(default_factory=dict)
    message_url: str | None = None


@dataclass(slots=True)
class PersonalWrapped:
    """Персональная сводка пользователя за год."""

    user_id: int
    period_label: str
    messages: int
    voice_seconds: int
    game_seconds: int
    reactions_received: int
    favorite_game: str | None
    top_games: list[tuple[str, int]] = field(default_factory=list)
    message_rank: int | None = None
    voice_rank: int | None = None
    reaction_rank: int | None = None
    reaction_total: int = 0
    total_users: int = 0
    footnote: str | None = None

    previous: dict[str, int] = field(default_factory=dict)


def _period_label(scope: WrappedScope, year: int, month: int | None) -> str:
    if scope == "monthly" and month is not None:
        return f"{MONTH_NAMES_RU.get(month, month)} {year}"
    return f"{year} год"


async def build_server_wrapped(
    *,
    scope: WrappedScope,
    year: int,
    month: int | None,
    stats_mgr: UserStatsDataManager,
    activity_mgr: ActivityDataManager,
    reactions_mgr: TopReactionsDataManager,
    top_limit: int,
    footnote: str | None = None,
    data_since: str | None = None,
    allowed_channel_ids: set[int] | None = None,
    excluded_message_ids: set[int] | None = None,
    excluded_user_ids: set[int] | None = None,
    ignore_self_reactions: bool = True,
    guild_id: int | None = None,
) -> ServerWrapped:
    """Строит серверную wrapped-сводку за период."""
    from utils.wrapped.monthly import build_period_wrapped
    from utils.wrapped_data_manager import WrappedDataManager

    if scope == "monthly" and month is None:
        raise ValueError("Для месячного wrapped нужен номер месяца")
    return await build_period_wrapped(
        year=year,
        month=month if scope == "monthly" else None,
        manager=WrappedDataManager(),
        reactions_mgr=reactions_mgr,
        top_limit=top_limit,
        data_since=data_since,
        allowed_channel_ids=allowed_channel_ids or set(),
        excluded_message_ids=excluded_message_ids or set(),
        excluded_user_ids=excluded_user_ids or set(),
        ignore_self_reactions=ignore_self_reactions,
        guild_id=guild_id,
    )


async def build_personal_wrapped(
    *,
    user_id: int,
    year: int,
    stats_mgr: UserStatsDataManager,
    activity_mgr: ActivityDataManager,
    reactions_mgr: TopReactionsDataManager,
    footnote: str | None = None,
    data_since: str | None = None,
) -> PersonalWrapped:
    """Строит персональную годовую сводку пользователя (с рангами по серверу)."""
    from utils.time_utils import moscow_today
    from utils.wrapped.monthly import previous_snapshot
    from utils.wrapped_data_manager import WrappedDataManager

    if year > moscow_today().year:
        raise ValueError("Нельзя построить wrapped за будущий год")
    manager = WrappedDataManager()
    snapshot = await manager.get_year(year)
    user_totals = snapshot.users
    game_per_user = {uid: sum(games.values()) for uid, games in snapshot.games.items()}
    entries = await reactions_mgr.get_top_authors("year", 100000, year=year, strict=True)
    reactions = {e.author_id: e.total_reactions for e in entries}
    available, old = await previous_snapshot(manager, snapshot, year, None, data_since)
    previous = {}
    if old is not None:
        # Отсутствие участника в архиве не означает подтверждённый ноль.
        if "messages" in available and user_id in old.users:
            previous["messages"] = old.users[user_id].messages
            previous["voice"] = old.users[user_id].voice_seconds
        if "games" in available and user_id in old.games:
            previous["games"] = sum(old.games[user_id].values())

    mine = user_totals.get(user_id, UserTotals(user_id=user_id, messages=0, voice_seconds=0))

    msg_ranked = sorted(user_totals.values(), key=lambda t: (-t.messages, t.user_id))
    voice_ranked = sorted(user_totals.values(), key=lambda t: (-t.voice_seconds, t.user_id))
    message_rank = next(
        (i for i, t in enumerate(msg_ranked, 1) if t.user_id == user_id and t.messages > 0), None
    )
    voice_rank = next(
        (i for i, t in enumerate(voice_ranked, 1) if t.user_id == user_id and t.voice_seconds > 0),
        None,
    )

    react_ranked = sorted(reactions.items(), key=lambda kv: (-kv[1], kv[0]))
    reaction_rank = (
        next((i for i, (uid, _) in enumerate(react_ranked, 1) if uid == user_id), None)
        if reactions.get(user_id, 0) > 0
        else None
    )

    my_games = snapshot.games.get(user_id, {})
    top_games = sorted(my_games.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    favorite_game = top_games[0][0] if top_games else None

    return PersonalWrapped(
        user_id=user_id,
        period_label=_period_label("yearly", year, None),
        messages=mine.messages,
        voice_seconds=mine.voice_seconds,
        game_seconds=game_per_user.get(user_id, 0),
        reactions_received=reactions.get(user_id, 0),
        favorite_game=favorite_game,
        top_games=top_games,
        message_rank=message_rank,
        voice_rank=voice_rank,
        reaction_rank=reaction_rank,
        reaction_total=len(reactions),
        total_users=len(user_totals),
        footnote=footnote,
        previous=previous,
    )


def _fmt_hm(seconds: int) -> str:
    """Короткий формат времени (например, "5ч 12м")."""
    if seconds <= 0:
        return "0 мин"
    if seconds < 60:
        return "< 1 мин"
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours > 0:
        return (
            f"{hours:,} ч {minutes} мин".replace(",", " ")
            if minutes
            else f"{hours:,} ч".replace(",", " ")
        )
    return f"{minutes} мин"
