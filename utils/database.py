"""Модуль для инициализации базы данных SQLite и определения ее схемы."""
import aiosqlite
import logging
from pathlib import Path

logger = logging.getLogger("bot.database")

# Определяем путь к файлу БД относительно директории проекта
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "bot_data.db"

async def initialize_database() -> None:
    """
    Инициализирует базу данных SQLite.
    Создает файл БД и необходимые таблицы, если они не существуют.
    
    Raises:
        Exception: Если произошла критическая ошибка при инициализации БД.
                  Исключение передается дальше, чтобы бот не запустился с нерабочей БД.
    """
    try:
        # Создаем директорию data, если ее нет
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(DB_PATH) as db:
            # Таблица для привязок аккаунтов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    discord_user_id INTEGER NOT NULL,
                    steam_id INTEGER NOT NULL,
                    PRIMARY KEY (discord_user_id, steam_id)
                )
            """)
            logger.info("Таблица 'links' проверена/создана.")

            # Таблица для дневной статистики
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_activity (
                    discord_user_id INTEGER NOT NULL,
                    game_name TEXT NOT NULL,
                    date TEXT NOT NULL, -- Формат YYYY-MM-DD
                    seconds_played_today INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (discord_user_id, game_name, date)
                )
            """)
            # Индекс для быстрого поиска по дате
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_daily_activity_date ON daily_activity (date);
            """)
            logger.info("Таблица 'daily_activity' и индекс проверены/созданы.")

            # Таблица для месячной агрегированной статистики
            await db.execute("""
                CREATE TABLE IF NOT EXISTS monthly_activity (
                    discord_user_id INTEGER NOT NULL,
                    game_name TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    total_seconds_in_month INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (discord_user_id, game_name, year, month)
                )
            """)
            # Индекс для быстрого поиска по пользователю, году и месяцу
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_monthly_activity_user_month ON monthly_activity (discord_user_id, year, month);
            """)
            logger.info("Таблица 'monthly_activity' и индекс проверены/созданы.")
            
            # Таблица для реакций-ролей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS role_reactions (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    emoji TEXT NOT NULL,
                    role_id INTEGER NOT NULL,
                    description TEXT,
                    PRIMARY KEY (guild_id, message_id, emoji)
                )
            """)
            logger.info("Таблица 'role_reactions' проверена/создана.")
            
            # Таблица для Twitch-стримеров
            await db.execute("""
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
            """)
            # Индекс для быстрого поиска по имени пользователя
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_twitch_streamers_username ON twitch_streamers (twitch_username);
            """)
            logger.info("Таблица 'twitch_streamers' и индекс проверены/созданы.")

            await db.commit()
            logger.info(f"База данных инициализирована: {DB_PATH}")

    except Exception as e:
        logger.critical(f"Критическая ошибка при инициализации базы данных: {e}", exc_info=True)
        raise # Передаем исключение дальше, чтобы бот не запустился с нерабочей БД
