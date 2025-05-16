"""Модуль для инициализации базы данных SQLite и определения ее схемы.

Этот модуль отвечает за создание и инициализацию базы данных SQLite,
используемой ботом для хранения различных данных, таких как:
- Привязки аккаунтов Discord к Steam ID
- Статистика игровой активности пользователей (дневная и месячная)
- Настройки ролей по реакциям
- Информация о Twitch-стримерах для отслеживания

Модуль определяет схему базы данных и предоставляет функцию для ее инициализации.
"""

import logging
from pathlib import Path

import aiosqlite

logger: logging.Logger = logging.getLogger("bot.utils.database")

# Определяем путь к файлу БД относительно директории проекта
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DB_PATH: Path = BASE_DIR / "data" / "bot_data.db"


async def initialize_database() -> None:
    """Инициализирует базу данных SQLite.

    Создает файл БД и необходимые таблицы, если они не существуют:
    - links: Привязки аккаунтов Discord к Steam ID
    - daily_activity: Ежедневная статистика игровой активности
    - monthly_activity: Ежемесячная агрегированная статистика
    - role_reactions: Настройки ролей по реакциям
    - twitch_streamers: Информация о Twitch-стримерах

    Также создает необходимые индексы для оптимизации запросов.

    Raises:
        Exception: Если произошла критическая ошибка при инициализации БД.
                  Исключение передается дальше, чтобы бот не запустился с нерабочей БД.
    """
    try:
        # Создаем директорию data, если ее нет
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(DB_PATH) as db:
            # Таблица для привязок аккаунтов
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS links (
                    discord_user_id INTEGER NOT NULL,
                    steam_id INTEGER NOT NULL,
                    PRIMARY KEY (discord_user_id, steam_id)
                )
            """
            )
            logger.info("Таблица 'links' проверена/создана.")

            # Таблица для дневной статистики
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_activity (
                    discord_user_id INTEGER NOT NULL,
                    game_name TEXT NOT NULL,
                    date TEXT NOT NULL, -- Формат YYYY-MM-DD
                    seconds_played_today INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (discord_user_id, game_name, date)
                )
            """
            )
            # Индекс для быстрого поиска по дате
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_activity_date ON daily_activity (date);
            """
            )
            logger.info("Таблица 'daily_activity' и индекс проверены/созданы.")

            # Таблица для месячной агрегированной статистики
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS monthly_activity (
                    discord_user_id INTEGER NOT NULL,
                    game_name TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    total_seconds_in_month INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (discord_user_id, game_name, year, month)
                )
            """
            )
            # Индекс для быстрого поиска по пользователю, году и месяцу
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_monthly_activity_user_month
                ON monthly_activity (discord_user_id, year, month);
            """
            )
            logger.info("Таблица 'monthly_activity' и индекс проверены/созданы.")

            # Таблица для реакций-ролей
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS role_reactions (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    emoji TEXT NOT NULL,
                    role_id INTEGER NOT NULL,
                    description TEXT,
                    PRIMARY KEY (guild_id, message_id, emoji)
                )
            """
            )
            logger.info("Таблица 'role_reactions' проверена/создана.")

            # Таблица для Twitch-стримеров
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS twitch_streamers (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    twitch_username TEXT NOT NULL,
                    twitch_id TEXT,
                    is_live BOOLEAN DEFAULT 0,
                    last_stream_id TEXT,
                    last_notification_time INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, twitch_username)
                )
            """
            )
            # Индекс для быстрого поиска по имени пользователя
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_twitch_streamers_username
                ON twitch_streamers (twitch_username);
            """
            )
            logger.info("Таблица 'twitch_streamers' и индекс проверены/созданы.")

            await db.commit()
            logger.info(f"База данных инициализирована: {DB_PATH}")

    except Exception as e:
        logger.critical(f"Критическая ошибка при инициализации базы данных: {e}", exc_info=True)
        raise  # Передаем исключение дальше, чтобы бот не запустился с нерабочей БД
