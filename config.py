"""
Загрузка конфигурации бота из JSON-файла.

Этот модуль отвечает за загрузку конфигурационных параметров бота из JSON-файла.
Он предоставляет функцию для чтения файла конфигурации и обработки возможных ошибок,
таких как отсутствие файла или некорректный формат JSON.
"""

import json
import logging
from typing import Any, Dict

logger: logging.Logger = logging.getLogger("bot.config")  # Используем иерархическое имя логгера


def load_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию из файла data/config.json.

    Читает JSON-файл с конфигурацией и преобразует его в словарь Python.
    Обрабатывает возможные ошибки, такие как отсутствие файла или некорректный формат.

    Returns:
        Dict[str, Any]: Словарь с конфигурационными параметрами бота.
        В случае ошибки возвращает словарь с BOT_TOKEN=None.

    Raises:
        FileNotFoundError: Если файл конфигурации не найден.
        Exception: При других ошибках чтения или парсинга файла.
    """
    config_path: str = "data/config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config: Dict[str, Any] = json.load(f)
            return config
    except FileNotFoundError:
        logger.critical(f"Файл конфигурации не найден: {config_path}")
        return {"BOT_TOKEN": None}  # Возвращаем словарь с None токеном, чтобы бот не запустился
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return {"BOT_TOKEN": None}
