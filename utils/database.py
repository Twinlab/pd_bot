"""Модуль для инициализации базы данных Tortoise ORM.

Этот модуль отвечает за настройку и инициализацию подключения к базе данных SQLite
с использованием Tortoise ORM.
"""

import logging
from pathlib import Path

from tortoise import Tortoise

logger: logging.Logger = logging.getLogger("bot.utils.database")

# Определяем путь к файлу БД относительно директории проекта
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DB_PATH: Path = BASE_DIR / "data" / "bot_data.db"


async def initialize_database() -> None:
    """Инициализирует Tortoise ORM.

    Настраивает подключение к базе данных SQLite и генерирует схемы таблиц,
    если они отсутствуют.
    """
    try:
        # Создаем директорию data, если ее нет
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Даты храним наивно в UTC; не включать use_tz — сырой SQL топ-реакций и
        # уже накопленные записи рассчитывают на формат без таймзонного суффикса.
        await Tortoise.init(
            db_url=f"sqlite://{DB_PATH}",
            modules={"models": ["utils.models"]},
            use_tz=False,
        )
        # Генерируем схемы (создаем таблицы), если их нет
        await Tortoise.generate_schemas()
        # WAL даёт параллельные чтения с записью; busy_timeout снимает
        # `database is locked` при коротких конкурентных транзакциях.
        # Tortoise.get_connection — кросс-совместимо с 0.25.x и 1.x; модульный
        # `from tortoise import connections` в 1.x требует активного контекста.
        conn = Tortoise.get_connection("default")
        await conn.execute_script(
            "PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL;PRAGMA busy_timeout=5000;"
        )
        logger.info(f"База данных инициализирована (Tortoise ORM, WAL): {DB_PATH}")

    except Exception as e:
        logger.critical(f"Критическая ошибка при инициализации базы данных: {e}", exc_info=True)
        raise


async def close_database() -> None:
    """Закрывает подключение к базе данных."""
    await Tortoise.close_connections()
    logger.info("Подключение к базе данных закрыто.")
