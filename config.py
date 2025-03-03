import json
import os
import logging
 
logger = logging.getLogger("bot")
 
def load_config():
    """Загружает конфигурацию из файла config.json"""
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return {"BOT_TOKEN": None}
 
def load_user_links(user_links_file="data/user_links.json"):
    """Загружает привязки аккаунтов из файла и конвертирует их при необходимости"""
    if not os.path.exists(user_links_file):
        logger.info(f"Файл {user_links_file} не существует, создаем пустой словарь")
        return {}
 
    try:
        with open(user_links_file, "r") as f:
            data = json.load(f)
 
        # Если данные в старом формате (список), конвертируем
        if isinstance(data, list):
            logger.info(f"Данные в {user_links_file} в старом формате, конвертируем")
            new_data = {}
            for item in data:
                if isinstance(item, dict) and "user" in item and "links" in item:
                    user_id = str(item["user"])
                    new_data[user_id] = item["links"]
 
            # Сохраняем конвертированные данные
            with open(user_links_file, "w") as f:
                json.dump(new_data, f, indent=4)
 
            logger.info(f"Данные в {user_links_file} были конвертированы в новый формат")
            return new_data
 
        # Если данные уже в новом формате (словарь)
        elif isinstance(data, dict):
            logger.info(f"Данные в {user_links_file} уже в новом формате")
            return data
 
        # Если формат неизвестен
        else:
            logger.warning(f"Неизвестный формат данных в {user_links_file}")
            return {}
 
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в {user_links_file}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке {user_links_file}: {e}")
        return {}