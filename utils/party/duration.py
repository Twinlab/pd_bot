"""Проверка выбранного московского времени игры и границ расписания."""

import re
from datetime import UTC, date, datetime, time, timedelta

from utils.time_utils import MOSCOW_TZ


def parse_start_time(
    day: str,
    clock: str,
    *,
    now: datetime,
    min_minutes: int = 1,
    max_minutes: int = 7 * 24 * 60,
) -> datetime:
    """Преобразует выбранный день и московское время в фиксированный момент UTC.

    Args:
        day: Дата из меню в формате YYYY-MM-DD.
        clock: Часы и минуты, например 21:30.
        now: Текущий момент с часовым поясом.
        min_minutes: Минимальный запас времени до начала.
        max_minutes: Максимальное расстояние до начала.

    Returns:
        Начало игры в UTC; прошедшее время не переносится на завтра автоматически.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Для проверки времени нужен часовой пояс")
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", clock.strip())
    if match is None:
        raise ValueError("Введи время по Москве в формате ЧЧ:ММ, например 21:30.")
    try:
        selected_day = date.fromisoformat(day)
    except ValueError:
        raise ValueError("Выбери день сбора заново.") from None
    start = datetime.combine(
        selected_day, time(int(match[1]), int(match[2])), tzinfo=MOSCOW_TZ
    ).astimezone(UTC)
    if start <= now:
        raise ValueError("Это время уже прошло. Выбери более позднее время или другой день.")
    if start - now < timedelta(minutes=min_minutes):
        raise ValueError(f"До начала должно оставаться хотя бы {min_minutes} мин.")
    if start - now > timedelta(minutes=max_minutes):
        raise ValueError(
            f"Сбор можно назначить не дальше чем на {max_minutes // 1440} дней вперёд."
        )
    return start


def parse_minutes(value: int, *, min_minutes: int, max_minutes: int) -> timedelta:
    """Превращает число минут в :class:`~datetime.timedelta` с проверкой границ.

    Args:
        value: Сколько минут хочет инициатор.
        min_minutes: Минимально допустимое значение (включительно).
        max_minutes: Максимально допустимое значение (включительно).

    Returns:
        :class:`~datetime.timedelta` соответствующей длительности.

    Raises:
        ValueError: Если ``value`` вне диапазона ``[min_minutes, max_minutes]``.
            Сообщение готово к показу пользователю.
    """
    if value < min_minutes:
        raise ValueError(f"Минимум — {min_minutes} мин.")
    if value > max_minutes:
        raise ValueError(f"Максимум — {max_minutes} мин.")
    return timedelta(minutes=value)
