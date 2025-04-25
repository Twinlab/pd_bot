import asyncio
import logging
import os
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Any

# Настройка базового логирования для скрипта
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("migration_script")

# --- Конфигурация ---
# Убедитесь, что пути соответствуют вашей структуре
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bot_data.db"
LINKS_JSON_PATH = DATA_DIR / "user_links.json"
ACTIVITY_JSON_PATH = DATA_DIR / "user_activities.json" # Дневной файл
MONTHLY_JSON_PATH = DATA_DIR / "monthly_activities.json" # Месячный файл
ARCHIVE_DIR = DATA_DIR / "activity_archives"

# --- Вспомогательные функции (синхронные, т.к. скрипт одноразовый) ---

def _safe_load_json(file_path: Path) -> Optional[Any]:
    """Безопасно загружает JSON из файла."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        logger.warning(f"Файл {file_path} не найден или пуст.")
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в {file_path}. Файл может быть поврежден.")
        return None
    except Exception as e:
        logger.error(f"Не удалось прочитать JSON файл {file_path}: {e}")
        return None

# --- Основная логика миграции ---

async def migrate_data():
    """Выполняет миграцию данных из JSON в SQLite."""
    logger.info("--- Начало миграции данных в SQLite ---")

    # Импортируем утилиты БД ПОСЛЕ настройки путей
    try:
        from utils.database import initialize_database, DB_PATH as UTIL_DB_PATH
        from utils.links_data_manager import LinksDataManager
        from utils.activity_data_manager import ActivityDataManager
        # Проверяем, что пути совпадают
        if str(DB_PATH) != UTIL_DB_PATH:
             logger.warning(f"Путь к БД в скрипте ({DB_PATH}) отличается от пути в utils ({UTIL_DB_PATH}). Используется путь из скрипта.")
    except ImportError as e:
        logger.critical(f"Не удалось импортировать утилиты. Убедитесь, что скрипт запущен из корневой директории проекта: {e}")
        return

    # 1. Инициализация БД (создание файла и таблиц, если их нет)
    logger.info("Шаг 1: Инициализация базы данных...")
    try:
        await initialize_database()
    except Exception as e:
        logger.critical(f"Не удалось инициализировать базу данных. Миграция прервана. Ошибка: {e}")
        return
    logger.info("База данных успешно инициализирована.")

    # 2. Миграция привязок
    logger.info("\nШаг 2: Миграция привязок аккаунтов...")
    links_migrator = LinksDataManager(db_path=str(DB_PATH))
    try:
        migrated_links_count = await links_migrator.migrate_links_from_json(str(LINKS_JSON_PATH))
        logger.info(f"Миграция привязок завершена. Обработано записей: {migrated_links_count}")
    except Exception as e:
        logger.error(f"Произошла ошибка во время миграции привязок: {e}", exc_info=True)

    # 3. Миграция статистики активности
    logger.info("\nШаг 3: Миграция статистики активности...")
    activity_migrator = ActivityDataManager(db_path=str(DB_PATH))
    try:
        # Используем встроенный метод миграции из ActivityDataManager, который мы добавили ранее
        await activity_migrator.migrate_activity_from_json()
        logger.info("Миграция статистики активности завершена.")
    except Exception as e:
        logger.error(f"Произошла ошибка во время миграции статистики активности: {e}", exc_info=True)


    logger.info("\n--- Миграция данных в SQLite завершена ---")
    logger.warning("ВАЖНО: Убедитесь, что миграция прошла успешно, проверив содержимое базы данных.")
    logger.warning(f"После проверки вы можете заархивировать или удалить старые JSON файлы:")
    logger.warning(f"- {LINKS_JSON_PATH}")
    logger.warning(f"- {ACTIVITY_JSON_PATH}")
    logger.warning(f"- {MONTHLY_JSON_PATH}")
    logger.warning(f"- Директорию: {ARCHIVE_DIR}")

if __name__ == "__main__":
    asyncio.run(migrate_data())
