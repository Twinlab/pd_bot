"""Утилиты для работы с когами Discord бота."""

import logging
from typing import Dict, Set

# Словарь для отслеживания загруженных когов
# Ключ - имя кога, значение - True, если уже было выведено сообщение о загрузке
_loaded_cogs: Dict[str, bool] = {}

# Множество для отслеживания имен когов, которые уже были загружены
# Используется для предотвращения дублирования сообщений
_cog_names: Set[str] = set()

# Получаем логгер для модуля
logger = logging.getLogger("bot.utils.cog_utils")


def log_cog_load(cog_name: str, source: str = "unknown") -> None:
    """
    Логирует загрузку кога, предотвращая дублирование сообщений.

    Args:
        cog_name: Имя кога (например, "LastMatchCog").
        source: Источник сообщения ("init" или "setup").
    """
    # Нормализуем имя кога (убираем "Cog" в конце, если есть)
    normalized_name = cog_name.replace("Cog", "").lower()

    # Если это первое сообщение о загрузке этого кога
    if normalized_name not in _cog_names:
        _cog_names.add(normalized_name)
        # Логируем загрузку
        logger.info(f"Ког {cog_name} успешно загружен.")
        return

    # Если это не первое сообщение, просто игнорируем его
    # Это предотвращает дублирование в логах
    return
