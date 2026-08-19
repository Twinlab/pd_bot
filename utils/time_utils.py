"""Общие тайм-зонные константы и вспомогалки.

Один источник истины для всего проекта, чтобы каждый ког не объявлял
``ZoneInfo("Europe/Moscow")`` у себя.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def moscow_today() -> date:
    """Возвращает текущую календарную дату в московском часовом поясе."""
    return datetime.now(MOSCOW_TZ).date()


def split_interval_by_local_date(
    started_at: datetime,
    ended_at: datetime,
    *,
    timezone: ZoneInfo = MOSCOW_TZ,
) -> list[tuple[date, int]]:
    """Разбивает интервал на целые секунды по локальным календарным датам.

    Сумма частей всегда равна целой длительности исходного интервала. Доли
    секунды около полуночи относятся к следующему дню только после пересечения
    фактической границы, поэтому периодические flush не накапливают округление.

    Args:
        started_at: Начало интервала с указанным часовым поясом.
        ended_at: Конец интервала с указанным часовым поясом.
        timezone: Пояс, календарные границы которого используются.

    Returns:
        Список пар ``(дата, секунды)`` в хронологическом порядке.

    Raises:
        ValueError: Если передан naive datetime.
    """
    if started_at.tzinfo is None or ended_at.tzinfo is None:
        raise ValueError("Границы интервала должны содержать часовой пояс")

    total_seconds = int((ended_at - started_at).total_seconds())
    if total_seconds <= 0:
        return []

    result: list[tuple[date, int]] = []
    cursor = started_at.astimezone(UTC)
    remaining = total_seconds

    while remaining > 0:
        local_cursor = cursor.astimezone(timezone)
        next_date = local_cursor.date() + timedelta(days=1)
        next_midnight = datetime.combine(next_date, time.min, tzinfo=timezone).astimezone(UTC)
        seconds_until_midnight = int((next_midnight - cursor).total_seconds())

        if seconds_until_midnight <= 0:
            cursor = next_midnight
            continue

        chunk = min(remaining, seconds_until_midnight)
        result.append((local_cursor.date(), chunk))
        cursor += timedelta(seconds=chunk)
        remaining -= chunk

    return result
