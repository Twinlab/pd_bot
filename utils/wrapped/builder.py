"""Сбор данных для wrapped-сводок.

Объединяет три источника: статистику сообщений/голоса
(:class:`~utils.user_stats_data_manager.UserStatsDataManager`), игровую активность
(:class:`~utils.activity_data_manager.ActivityDataManager`) и лидерборд реакций
(:class:`~utils.top_reactions_data_manager.TopReactionsDataManager`). На выходе —
структуры, которые рендер превращает в картинку.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from utils.activity_data_manager import ActivityDataManager
from utils.top_reactions_data_manager import TopReactionsDataManager
from utils.user_stats_data_manager import UserStatsDataManager, UserTotals

logger = logging.getLogger("bot.utils.wrapped.builder")

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


def _period_label(scope: WrappedScope, year: int, month: int | None) -> str:
    if scope == "monthly" and month is not None:
        return f"{MONTH_NAMES_RU.get(month, month)} {year}"
    return f"{year} год"


async def _gather_user_totals(
    scope: WrappedScope,
    year: int,
    month: int | None,
    stats_mgr: UserStatsDataManager,
) -> dict[int, UserTotals]:
    """Собирает тоталы сообщений/голоса, подмешивая ещё не перенесённые дни."""
    if scope == "monthly" and month is not None:
        monthly = await stats_mgr.get_monthly_totals(year, month)
        daily = await stats_mgr.get_daily_totals_by_prefix(f"{year}-{month:02d}")
    else:
        monthly = await stats_mgr.get_yearly_totals(year)
        daily = await stats_mgr.get_daily_totals_by_prefix(str(year))
    return stats_mgr.merge_totals(monthly, daily)


async def _gather_game_totals(
    scope: WrappedScope,
    year: int,
    month: int | None,
    activity_mgr: ActivityDataManager,
) -> tuple[dict[int, int], dict[str, int]]:
    """Возвращает (игровые секунды на пользователя, игровые секунды на игру)."""
    per_user: dict[int, int] = defaultdict(int)
    per_game: dict[str, int] = defaultdict(int)

    if scope == "monthly" and month is not None:
        months = [(year, month)]
    else:
        months = [(year, m) for m in range(1, 13)]

    for y, m in months:
        agg = await activity_mgr.get_aggregated_monthly_stats(y, m)
        for uid, games in agg.items():
            for game, seconds in games.items():
                per_user[uid] += seconds
                per_game[game] += seconds

    return dict(per_user), dict(per_game)


async def _reactions_by_author(
    scope: WrappedScope,
    year: int,
    month: int | None,
    reactions_mgr: TopReactionsDataManager,
    limit: int,
) -> dict[int, int]:
    """Возвращает {author_id: полученные реакции} за период."""
    try:
        if scope == "monthly" and month is not None:
            entries = await reactions_mgr.get_top_authors("month", limit, year=year, month=month)
        else:
            entries = await reactions_mgr.get_top_authors("year", limit, year=year)
        return {e.author_id: e.total_reactions for e in entries}
    except Exception as e:
        logger.error(f"Ошибка получения топа авторов реакций: {e}", exc_info=True)
        return {}


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
) -> ServerWrapped:
    """Строит серверную wrapped-сводку за период."""
    user_totals = await _gather_user_totals(scope, year, month, stats_mgr)
    game_per_user, game_per_game = await _gather_game_totals(scope, year, month, activity_mgr)
    reactions = await _reactions_by_author(scope, year, month, reactions_mgr, max(top_limit, 50))

    top_messages = [
        NamedValue(t.user_id, t.messages)
        for t in UserStatsDataManager.top_by_messages(user_totals, top_limit)
    ]
    top_voice = [
        NamedValue(t.user_id, t.voice_seconds)
        for t in UserStatsDataManager.top_by_voice(user_totals, top_limit)
    ]
    top_games = sorted(game_per_game.items(), key=lambda kv: kv[1], reverse=True)[:top_limit]

    total_messages = sum(t.messages for t in user_totals.values())
    total_voice = sum(t.voice_seconds for t in user_totals.values())
    total_game = sum(game_per_game.values())
    active_users = len(
        {uid for uid, t in user_totals.items() if t.messages > 0 or t.voice_seconds > 0}
        | set(game_per_user)
    )

    nominations: list[Nomination] = []
    if top_messages:
        nominations.append(
            Nomination(
                "💬",
                "По сообщениям",
                top_messages[0].user_id,
                f"{top_messages[0].value} сообщ.",
            )
        )
    if top_voice:
        nominations.append(
            Nomination(
                "🎙️",
                "По войсу",
                top_voice[0].user_id,
                _fmt_hm(top_voice[0].value),
            )
        )
    if game_per_user:
        gamer_id = max(game_per_user, key=lambda uid: game_per_user[uid])
        nominations.append(Nomination("🎮", "Геймер", gamer_id, _fmt_hm(game_per_user[gamer_id])))
    if reactions:
        magnet_id = max(reactions, key=lambda uid: reactions[uid])
        nominations.append(
            Nomination("⭐", "По реакциям", magnet_id, f"{reactions[magnet_id]} реакц.")
        )

    return ServerWrapped(
        period_label=_period_label(scope, year, month),
        scope=scope,
        total_messages=total_messages,
        total_voice_seconds=total_voice,
        total_game_seconds=total_game,
        active_users=active_users,
        top_messages=top_messages,
        top_voice=top_voice,
        top_games=top_games,
        nominations=nominations,
        footnote=footnote,
    )


async def build_personal_wrapped(
    *,
    user_id: int,
    year: int,
    stats_mgr: UserStatsDataManager,
    activity_mgr: ActivityDataManager,
    reactions_mgr: TopReactionsDataManager,
    footnote: str | None = None,
) -> PersonalWrapped:
    """Строит персональную годовую сводку пользователя (с рангами по серверу)."""
    user_totals = await _gather_user_totals("yearly", year, None, stats_mgr)
    game_per_user, _ = await _gather_game_totals("yearly", year, None, activity_mgr)
    reactions = await _reactions_by_author("yearly", year, None, reactions_mgr, 100000)

    mine = user_totals.get(user_id, UserTotals(user_id=user_id, messages=0, voice_seconds=0))

    msg_ranked = sorted(user_totals.values(), key=lambda t: t.messages, reverse=True)
    voice_ranked = sorted(user_totals.values(), key=lambda t: t.voice_seconds, reverse=True)
    message_rank = next(
        (i for i, t in enumerate(msg_ranked, 1) if t.user_id == user_id and t.messages > 0), None
    )
    voice_rank = next(
        (i for i, t in enumerate(voice_ranked, 1) if t.user_id == user_id and t.voice_seconds > 0),
        None,
    )

    react_ranked = sorted(reactions.items(), key=lambda kv: kv[1], reverse=True)
    reaction_rank = (
        next((i for i, (uid, _) in enumerate(react_ranked, 1) if uid == user_id), None)
        if reactions.get(user_id, 0) > 0
        else None
    )

    my_games: dict[str, int] = {}
    for y, m in [(year, mm) for mm in range(1, 13)]:
        agg = await activity_mgr.get_aggregated_monthly_stats(y, m)
        for game, seconds in agg.get(user_id, {}).items():
            my_games[game] = my_games.get(game, 0) + seconds
    top_games = sorted(my_games.items(), key=lambda kv: kv[1], reverse=True)[:5]
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
    )


def _fmt_hm(seconds: int) -> str:
    """Короткий формат времени (например, "5ч 12м")."""
    if seconds <= 0:
        return "0м"
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours > 0:
        return f"{hours}ч {minutes}м" if minutes else f"{hours}ч"
    return f"{minutes}м"
