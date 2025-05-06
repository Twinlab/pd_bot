"""Загрузка конфигурации бота из JSON-файла."""
import json
import logging
from typing import Dict, Any

logger = logging.getLogger("bot.config")  # Используем иерархическое имя логгера

def load_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию из файла data/config.json.
    
    Returns:
        Dict[str, Any]: Словарь с конфигурационными параметрами бота.
        В случае ошибки возвращает словарь с BOT_TOKEN=None.
    """
    config_path = "data/config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.critical(f"Файл конфигурации не найден: {config_path}")
        return {"BOT_TOKEN": None} # Возвращаем словарь с None токеном, чтобы бот не запустился
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return {"BOT_TOKEN": None}
