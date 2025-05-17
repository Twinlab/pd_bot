"""Утилиты для работы с когами Discord бота."""

import logging
from typing import Set

# Множество для отслеживания имен когов, которые уже были загружены
# Используется для предотвращения дублирования сообщений
_cog_names: Set[str] = set()

# Получаем логгер для модуля
logger = logging.getLogger("bot.utils.cog_utils")


def should_log_cog_load(cog_name: str) -> bool:
    """
    Проверяет, нужно ли логировать загрузку кога.

    Возвращает True только для первого сообщения о загрузке кога,
    что позволяет избежать дублирования сообщений в логах.

    Args:
        cog_name: Имя кога (например, "LastMatchCog").

    Returns:
        bool: True, если это первое сообщение о загрузке кога, иначе False.
    """
    # Нормализуем имя кога (убираем "Cog" в конце, если есть)
    normalized_name = cog_name.replace("Cog", "").lower()

    # Если это первое сообщение о загрузке этого кога
    if normalized_name not in _cog_names:
        _cog_names.add(normalized_name)
        return True

    # Если это не первое сообщение, возвращаем False
    return False


def log_cog_load(cog_name: str, source: str = "unknown") -> None:
    """
    Логирует загрузку кога, предотвращая дублирование сообщений.

    Эта функция устарела и оставлена для обратной совместимости.
    Рекомендуется использовать should_log_cog_load().

    Args:
        cog_name: Имя кога (например, "LastMatchCog").
        source: Источник сообщения ("init" или "setup").
    """
    # Проверяем, нужно ли логировать загрузку
    if should_log_cog_load(cog_name):
        # Ничего не делаем, так как логирование должно происходить в самом коге
        pass
