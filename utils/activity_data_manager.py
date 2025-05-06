"""Менеджер данных для отслеживания игровой активности пользователей с использованием SQLite."""
import aiosqlite
import logging
from datetime import datetime, date # timedelta и asyncio не используются напрямую
from collections import defaultdict
from typing import Dict, Any, Tuple, List
# import asyncio # asyncio не используется напрямую

from .database import DB_PATH

logger = logging.getLogger("bot.activity_db")

class ActivityDataManager:
    """
    Управляет данными об игровой активности пользователей с использованием SQLite.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        # Данные в памяти больше не храним здесь, все идет через БД
        logger.info(f"Инициализация ActivityDataManager с БД: {self.db_path}")

    async def update_activity(self, user_id: int, game_name: str, elapsed_seconds: int):
        """
        Обновляет дневную статистику активности в БД SQLite.
        Добавляет время к записи за текущий день или создает новую.
        """
        if elapsed_seconds <= 0:
            return

        today_str = date.today().isoformat() # Формат YYYY-MM-DD

        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO daily_activity (discord_user_id, game_name, date, seconds_played_today)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(discord_user_id, game_name, date) DO UPDATE SET
                    seconds_played_today = seconds_played_today + excluded.seconds_played_today;
                """, (user_id, game_name, today_str, elapsed_seconds))
                await db.commit()
                logger.debug(f"Обновлена дневная активность в БД для {user_id} - {game_name} ({today_str}): +{elapsed_seconds} сек.")
        except Exception as e:
            logger.error(f"Ошибка при обновлении daily_activity в БД: {e}", exc_info=True)

    async def get_daily_stats(self, target_date: date) -> Dict[int, Dict[str, int]]:
        """
        Получает всю статистику активности за указанную дату из БД.
        """
        target_date_str = target_date.isoformat()
        daily_stats: Dict[int, Dict[str, int]] = defaultdict(dict)
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("""
                    SELECT discord_user_id, game_name, seconds_played_today
                    FROM daily_activity
                    WHERE date = ? AND seconds_played_today > 0
                """, (target_date_str,)) as cursor:
                    async for row in cursor:
                        user_id, game_name, seconds = row
                        daily_stats[user_id][game_name] = seconds
            logger.info(f"Загружена дневная статистика за {target_date_str} из БД: {len(daily_stats)} пользователей.")
            return dict(daily_stats)
        except Exception as e:
            logger.error(f"Ошибка при получении daily_stats из БД за {target_date_str}: {e}", exc_info=True)
            return {}

    async def transfer_daily_to_monthly(self, target_date: date) -> bool:
        """
        Переносит агрегированные данные из daily_activity за указанную дату
        в monthly_activity и удаляет перенесенные дневные записи.
        Выполняется в одной транзакции.
        Возвращает True в случае успеха, False при ошибке.
        """
        target_date_str = target_date.isoformat()
        year = target_date.year
        month = target_date.month
        success = False
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Начинаем транзакцию вручную
                await db.execute("BEGIN")
                try:
                    # 1. Агрегируем и обновляем/вставляем в monthly_activity
                    await db.execute("""
                        INSERT INTO monthly_activity (discord_user_id, game_name, year, month, total_seconds_in_month)
                        SELECT
                            discord_user_id,
                            game_name,
                            ?, ?,
                            SUM(seconds_played_today)
                        FROM daily_activity
                        WHERE date = ? AND seconds_played_today > 0
                        GROUP BY discord_user_id, game_name
                        ON CONFLICT(discord_user_id, game_name, year, month) DO UPDATE SET
                        total_seconds_in_month = total_seconds_in_month + excluded.total_seconds_in_month;
                    """, (year, month, target_date_str))
                    logger.info(f"Данные за {target_date_str} агрегированы и добавлены в monthly_activity за {year}-{month:02d}.")

                    # 2. Удаляем обработанные записи из daily_activity
                    await db.execute("DELETE FROM daily_activity WHERE date = ?", (target_date_str,))
                    logger.info(f"Удалены записи из daily_activity за {target_date_str}.")

                    # Коммитим транзакцию
                    await db.commit()
                    success = True
                    logger.info(f"Транзакция переноса данных за {target_date_str} успешно завершена.")

                except Exception as inner_e:
                    # Если ошибка внутри транзакции, откатываем изменения
                    logger.error(f"Ошибка внутри транзакции переноса данных за {target_date_str}, откатываем: {inner_e}", exc_info=True)
                    await db.rollback()
                    success = False

        except Exception as outer_e:
            logger.error(f"Ошибка подключения к БД при переносе данных за {target_date_str}: {outer_e}", exc_info=True)
            success = False

        return success

    async def get_monthly_stats(self, user_id: int, year: int, month: int) -> Dict[str, int]:
        """
        Получает статистику активности пользователя за указанный месяц и год из БД.
        """
        user_stats: Dict[str, int] = {}
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("""
                    SELECT game_name, total_seconds_in_month
                    FROM monthly_activity
                    WHERE discord_user_id = ? AND year = ? AND month = ? AND total_seconds_in_month > 0
                """, (user_id, year, month)) as cursor:
                    async for row in cursor:
                        game_name, seconds = row
                        user_stats[game_name] = seconds
            logger.debug(f"Загружена месячная статистика для {user_id} за {year}-{month:02d}: {len(user_stats)} игр.")
            return user_stats
        except Exception as e:
            logger.error(f"Ошибка при получении monthly_stats из БД для {user_id} ({year}-{month:02d}): {e}", exc_info=True)
            return {}

    async def get_aggregated_monthly_stats(self, year: int, month: int) -> Dict[int, Dict[str, int]]:
        """
        Получает всю статистику активности за указанный месяц и год из БД.
        Возвращает словарь {user_id: {game_name: seconds}}.
        """
        monthly_stats: Dict[int, Dict[str, int]] = defaultdict(dict)
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("""
                    SELECT discord_user_id, game_name, total_seconds_in_month
                    FROM monthly_activity
                    WHERE year = ? AND month = ? AND total_seconds_in_month > 0
                """, (year, month)) as cursor:
                    async for row in cursor:
                        user_id, game_name, seconds = row
                        monthly_stats[user_id][game_name] = seconds
            logger.info(f"Загружена агрегированная месячная статистика за {year}-{month:02d}: {len(monthly_stats)} пользователей.")
            return dict(monthly_stats)
        except Exception as e:
            logger.error(f"Ошибка при получении агрегированной monthly_stats из БД за {year}-{month:02d}: {e}", exc_info=True)
            return {}

    async def get_all_time_stats(self, user_id: int) -> Dict[str, int]:
        """
        Получает суммарную статистику активности пользователя за всё время из БД.
        """
        user_stats: Dict[str, int] = defaultdict(int)
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Суммируем данные из monthly_activity
                async with db.execute("""
                    SELECT game_name, SUM(total_seconds_in_month) as total_seconds
                    FROM monthly_activity
                    WHERE discord_user_id = ? AND total_seconds_in_month > 0
                    GROUP BY game_name
                """, (user_id,)) as cursor:
                    async for row in cursor:
                        game_name, seconds = row
                        user_stats[game_name] += seconds # Используем += на случай дублирования игры (хотя GROUP BY должен это исключить)

                # Добавляем данные из daily_activity за СЕГОДНЯШНИЙ день, так как они еще не в monthly_activity
                today_str = date.today().isoformat()
                async with db.execute("""
                    SELECT game_name, seconds_played_today
                    FROM daily_activity
                    WHERE discord_user_id = ? AND date = ? AND seconds_played_today > 0
                """, (user_id, today_str)) as cursor:
                     async for row in cursor:
                        game_name, seconds = row
                        user_stats[game_name] += seconds

            logger.debug(f"Загружена статистика за все время для {user_id}: {len(user_stats)} игр.")
            return dict(user_stats)
        except Exception as e:
            logger.error(f"Ошибка при получении all_time_stats из БД для {user_id}: {e}", exc_info=True)
            return {}
