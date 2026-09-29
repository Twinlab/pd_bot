"""Сбор месячного wrapped с динамикой и отдельными номинациями."""

import logging
from collections import defaultdict
from datetime import date

from utils.time_utils import MOSCOW_TZ, moscow_today
from utils.top_reactions_data_manager import TopReactionsDataManager
from utils.wrapped.builder import MONTH_NAMES_RU, NamedValue, Nomination, ServerWrapped
from utils.wrapped_data_manager import MonthlySnapshot, WrappedDataManager

logger = logging.getLogger("bot.wrapped.monthly")


def _totals(snapshot: MonthlySnapshot) -> dict[str, int]:
    active = {uid for uid, t in snapshot.users.items() if t.messages or t.voice_seconds}
    active.update(snapshot.games)
    return {
        "messages": sum(t.messages for t in snapshot.users.values()),
        "voice": sum(t.voice_seconds for t in snapshot.users.values()),
        "games": sum(sum(g.values()) for g in snapshot.games.values()),
        "users": len(active),
    }


def _plural(value: int, forms: tuple[str, str, str]) -> str:
    if 11 <= value % 100 <= 14:
        return forms[2]
    return forms[0] if value % 10 == 1 else forms[1] if 2 <= value % 10 <= 4 else forms[2]


async def build_monthly_wrapped(
    *,
    year: int,
    month: int,
    manager: WrappedDataManager,
    reactions_mgr: TopReactionsDataManager,
    top_limit: int,
    data_since: str | None,
    allowed_channel_ids: set[int],
    excluded_message_ids: set[int],
    excluded_user_ids: set[int],
    ignore_self_reactions: bool,
    guild_id: int | None,
) -> ServerWrapped:
    """Собирает месяц; сравнивает только закрытые периоды с доступной историей.

    Args:
        year: Год отчёта.
        month: Номер месяца.
        manager: Строгий источник месячных снимков.
        reactions_mgr: Источник рейтингов реакций.
        top_limit: Число строк рейтингов, не больше пяти.
        data_since: Подтверждённая дата начала сбора.
        allowed_channel_ids: Каналы, доступные всем участникам.
        excluded_message_ids: Служебные сообщения и ручные исключения.
        excluded_user_ids: Авторы и реакторы, исключённые из рейтинга.
        ignore_self_reactions: Исключать реакции автора.
        guild_id: Сервер для канонической ссылки на сообщение.

    Raises:
        Exception: Ошибка чтения текущего периода.
    """
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    previous_start = date(year - (month == 1), 12 if month == 1 else month - 1, 1)
    if start > moscow_today():
        raise ValueError("Нельзя построить wrapped за будущий месяц")
    current = await manager.get_month(year, month)
    totals = _totals(current)
    previous: dict[str, int] = {}
    try:
        since = date.fromisoformat(data_since) if data_since else None
    except ValueError:
        logger.warning("Некорректная дата начала сбора: сравнение wrapped отключено")
        since = None

    if since is not None and since <= previous_start and end <= moscow_today():
        try:
            old = await manager.get_month(previous_start.year, previous_start.month)
        except Exception:
            logger.exception("Предыдущий месяц недоступен: wrapped без сравнения")
        else:
            old_totals = _totals(old)
            # Отсутствие строк в истории само по себе не доказывает нулевую активность.
            if old.users:
                previous.update(messages=old_totals["messages"], voice=old_totals["voice"])
            if old.games:
                previous["games"] = old_totals["games"]
            if old.users and old.games:
                previous["users"] = old_totals["users"]

    limit = min(5, max(1, top_limit))
    top_messages = sorted(
        (NamedValue(uid, t.messages) for uid, t in current.users.items() if t.messages > 0),
        key=lambda entry: (-entry.value, entry.user_id),
    )[:limit]
    top_voice = sorted(
        (
            NamedValue(uid, t.voice_seconds)
            for uid, t in current.users.items()
            if t.voice_seconds > 0
        ),
        key=lambda entry: (-entry.value, entry.user_id),
    )[:limit]
    per_game: dict[str, int] = defaultdict(int)
    for games in current.games.values():
        for name, seconds in games.items():
            per_game[name] += seconds
    nominations: list[Nomination] = []
    diversity = {
        uid: sum(seconds > 3600 for seconds in games.values())
        for uid, games in current.games.items()
    }
    if any(diversity.values()):
        uid = min(diversity, key=lambda uid: (-diversity[uid], uid))
        count = diversity[uid]
        nominations.append(
            Nomination(
                "🎮",
                "Разнообразие игр",
                uid,
                f"{count} {_plural(count, ('игра', 'игры', 'игр'))}",
            )
        )

    leaders = await reactions_mgr.get_leaderboard(
        "month",
        1,
        year=year,
        month=month,
        allowed_channel_ids=allowed_channel_ids,
        excluded_message_ids=excluded_message_ids,
        excluded_user_ids=excluded_user_ids,
        ignore_self_reactions=ignore_self_reactions,
        timezone=MOSCOW_TZ,
        strict=True,
    )
    message_url = None
    if leaders:
        best = leaders[0]
        count = best.reactor_count
        nominations.append(
            Nomination(
                "💬",
                "Сообщение месяца",
                best.author_id,
                f"{count:,} {_plural(count, ('реакция', 'реакции', 'реакций'))}".replace(",", " "),
            )
        )
        if guild_id is not None and best.channel_id in allowed_channel_ids:
            message_url = (
                f"https://discord.com/channels/{guild_id}/{best.channel_id}/{best.message_id}"
            )

    if current.games:
        gamer = min(current.games, key=lambda uid: (-sum(current.games[uid].values()), uid))
        minutes = sum(current.games[gamer].values()) // 60
        detail = f"{minutes:,} мин".replace(",", " ") if minutes else "< 1 мин"
        nominations.append(Nomination("🎮", "Геймер", gamer, detail))
    authors = await reactions_mgr.get_top_authors(
        "month",
        1,
        year=year,
        month=month,
        allowed_channel_ids=allowed_channel_ids,
        excluded_message_ids=excluded_message_ids,
        excluded_user_ids=excluded_user_ids,
        ignore_self_reactions=ignore_self_reactions,
        timezone=MOSCOW_TZ,
        strict=True,
    )
    if authors:
        count = authors[0].total_reactions
        nominations.append(
            Nomination(
                "⭐",
                "По реакциям",
                authors[0].author_id,
                f"{count:,} {_plural(count, ('реакция', 'реакции', 'реакций'))}".replace(",", " "),
            )
        )

    return ServerWrapped(
        period_label=f"{MONTH_NAMES_RU[month]} {year}",
        scope="monthly",
        total_messages=totals["messages"],
        total_voice_seconds=totals["voice"],
        total_game_seconds=totals["games"],
        active_users=totals["users"],
        top_messages=top_messages,
        top_voice=top_voice,
        top_games=sorted(per_game.items(), key=lambda item: (-item[1], item[0]))[:5],
        nominations=nominations,
        previous=previous,
        message_url=message_url,
    )
