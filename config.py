import json
import os
import logging
 
logger = logging.getLogger("bot")
 
def load_config():
    """Загружает конфигурацию из файла data/config.json"""
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

# Функция load_user_links удалена, т.к. привязки теперь хранятся в SQLite
# и управляются через LinksDataManager.
# Логика миграции перенесена в LinksDataManager.migrate_links_from_json
