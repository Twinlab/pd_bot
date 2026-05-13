"""Валидация длительности сбора пати.

Команда ``/party`` принимает целое число минут — здесь мы проверяем диапазон
и превращаем его в :class:`datetime.timedelta`. Вынесено в отдельный модуль,
чтобы валидацию было удобно покрыть unit-тестами без поднятия Discord/конфига.
"""

from datetime import timedelta


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
