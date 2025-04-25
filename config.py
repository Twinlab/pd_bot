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
 
def load_user_links(user_links_file="data/user_links.json"):
    """
    Загружает привязки аккаунтов Dota 2 (Steam ID) к Discord ID из JSON-файла.
    Поддерживает конвертацию из старого формата (список словарей) в новый (словарь).
    """
    if not os.path.exists(user_links_file):
        logger.info(f"Файл {user_links_file} не существует, создаем пустой словарь")
        return {}
 
    try:
        with open(user_links_file, "r") as f:
            data = json.load(f)
 
        # Проверка и конвертация старого формата (список словарей)
        if isinstance(data, list):
            logger.info(f"Данные в {user_links_file} в старом формате, конвертируем...")
            new_data = {}
            for item in data:
                if isinstance(item, dict) and "user" in item and "links" in item:
                    user_id = str(item["user"])
                    new_data[user_id] = item["links"]
         
                    # Перезаписываем файл в новом формате
                    with open(user_links_file, "w", encoding="utf-8") as f:
                        json.dump(new_data, f, indent=4)
 
            logger.info(f"Данные в {user_links_file} были конвертированы в новый формат")
            return new_data
 
        # Обработка нового формата (словарь)
        elif isinstance(data, dict):
            # Данные уже в новом формате (словарь)
            return data
 
        # Неизвестный формат данных
        else:
            logger.warning(f"Неизвестный формат данных в {user_links_file}")
            return {}
 
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в {user_links_file}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке {user_links_file}: {e}")
        return {}
