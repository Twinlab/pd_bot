import aiosqlite
import logging
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Dict, Any, Tuple, List
import asyncio

# Импортируем путь к БД из database.py
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
                # Используем INSERT OR REPLACE или ON CONFLICT DO UPDATE
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

    # --- Методы для миграции (используются в migrate_to_sqlite.py) ---

    async def migrate_links_from_json(self, json_file_path: str = "data/user_links.json"):
        """Мигрирует данные о привязках из JSON в SQLite."""
        logger.info(f"Начало миграции привязок из {json_file_path}...")
        count = 0
        # Используем синхронный код для чтения JSON, так как это одноразовая операция
        try:
            import json as sync_json
            import os as sync_os
            if not sync_os.path.exists(json_file_path) or sync_os.path.getsize(json_file_path) == 0:
                logger.warning(f"Файл {json_file_path} не найден или пуст. Миграция привязок пропущена.")
                return

            with open(json_file_path, "r", encoding="utf-8") as f:
                data = sync_json.load(f)

            links_to_insert: List[Tuple[int, int]] = []
            if isinstance(data, dict): # Новый формат
                for user_id_str, steam_ids in data.items():
                    try:
                        user_id = int(user_id_str)
                        if isinstance(steam_ids, list):
                            for steam_id in steam_ids:
                                try:
                                    links_to_insert.append((user_id, int(steam_id)))
                                except (ValueError, TypeError):
                                    logger.warning(f"Некорректный steam_id '{steam_id}' для пользователя {user_id} в {json_file_path}")
                        else:
                             logger.warning(f"Некорректный формат steam_ids для пользователя {user_id} в {json_file_path}")
                    except ValueError:
                        logger.warning(f"Некорректный user_id '{user_id_str}' в {json_file_path}")
            elif isinstance(data, list): # Старый формат
                 logger.info("Обнаружен старый формат user_links.json, конвертируем...")
                 for item in data:
                     if isinstance(item, dict) and "user" in item and "links" in item:
                         try:
                             user_id = int(item["user"])
                             if isinstance(item["links"], list):
                                 for steam_id in item["links"]:
                                     try:
                                         links_to_insert.append((user_id, int(steam_id)))
                                     except (ValueError, TypeError):
                                         logger.warning(f"Некорректный steam_id '{steam_id}' для пользователя {user_id} в старом формате {json_file_path}")
                             else:
                                 logger.warning(f"Некорректный формат links для пользователя {user_id} в старом формате {json_file_path}")
                         except (ValueError, TypeError):
                             logger.warning(f"Некорректный user_id '{item.get('user')}' в старом формате {json_file_path}")
                     else:
                         logger.warning(f"Некорректный элемент в старом формате {json_file_path}: {item}")
            else:
                logger.error(f"Неизвестный формат данных в {json_file_path}. Миграция привязок прервана.")
                return

            if not links_to_insert:
                logger.info("Не найдено привязок для миграции.")
                return

            async with aiosqlite.connect(self.db_path) as db:
                await db.executemany("""
                    INSERT OR IGNORE INTO links (discord_user_id, steam_id) VALUES (?, ?)
                """, links_to_insert)
                await db.commit()
                count = len(links_to_insert) # Приблизительное количество, т.к. IGNORE может пропустить дубликаты

            logger.info(f"Миграция привязок завершена. Добавлено/проигнорировано {count} записей.")

        except Exception as e:
            logger.error(f"Ошибка во время миграции привязок: {e}", exc_info=True)

    async def migrate_activity_from_json(self):
        """
        Мигрирует данные активности из monthly_activities.json и activity_archives/*.json
        в таблицу monthly_activity SQLite.
        """
        logger.info("Начало миграции данных активности из JSON...")
        total_records_migrated = 0

        try:
            import json as sync_json
            import os as sync_os
            from pathlib import Path as SyncPath

            base_dir = SyncPath(self.db_path).parent.parent # /path/to/project
            data_dir = base_dir / "data"
            monthly_file = data_dir / "monthly_activities.json"
            archive_dir = data_dir / "activity_archives"

            records_to_insert: List[Tuple[int, str, int, int, int]] = []

            # 1. Обработка monthly_activities.json
            if monthly_file.exists() and monthly_file.stat().st_size > 0:
                logger.info(f"Обработка {monthly_file}...")
                try:
                    current_year = datetime.now().year
                    current_month = datetime.now().month
                    with open(monthly_file, "r", encoding="utf-8") as f:
                        data = sync_json.load(f)
                    if isinstance(data, dict):
                        for user_id_str, games in data.items():
                            try:
                                user_id = int(user_id_str)
                                if isinstance(games, dict):
                                    for game_name, seconds in games.items():
                                        if isinstance(seconds, int) and seconds > 0:
                                            records_to_insert.append((user_id, game_name, current_year, current_month, seconds))
                                        else:
                                             logger.warning(f"Некорректное время '{seconds}' для {user_id}-{game_name} в {monthly_file}")
                                else:
                                     logger.warning(f"Некорректный формат игр для {user_id} в {monthly_file}")
                            except ValueError:
                                logger.warning(f"Некорректный user_id '{user_id_str}' в {monthly_file}")
                    else:
                         logger.warning(f"Некорректный формат данных в {monthly_file}")
                except Exception as e:
                    logger.error(f"Ошибка при обработке {monthly_file}: {e}", exc_info=True)
            else:
                logger.info(f"{monthly_file} не найден или пуст, пропускаем.")

            # 2. Обработка архивов
            if archive_dir.exists() and archive_dir.is_dir():
                 logger.info(f"Обработка архивов в {archive_dir}...")
                 for archive_file in archive_dir.glob("activity_*.json"):
                     logger.info(f"Обработка архива {archive_file.name}...")
                     try:
                         parts = archive_file.stem.split('_') # activity_YYYY_MM
                         if len(parts) == 3:
                             year = int(parts[1])
                             month = int(parts[2])
                             with open(archive_file, "r", encoding="utf-8") as f:
                                 data = sync_json.load(f)
                             if isinstance(data, dict):
                                 for user_id_str, games in data.items():
                                     try:
                                         user_id = int(user_id_str)
                                         if isinstance(games, dict):
                                             for game_name, seconds in games.items():
                                                 if isinstance(seconds, int) and seconds > 0:
                                                     records_to_insert.append((user_id, game_name, year, month, seconds))
                                                 else:
                                                     logger.warning(f"Некорректное время '{seconds}' для {user_id}-{game_name} в {archive_file.name}")
                                         else:
                                             logger.warning(f"Некорректный формат игр для {user_id} в {archive_file.name}")
                                     except ValueError:
                                         logger.warning(f"Некорректный user_id '{user_id_str}' в {archive_file.name}")
                             else:
                                 logger.warning(f"Некорректный формат данных в {archive_file.name}")
                         else:
                             logger.warning(f"Некорректное имя архивного файла {archive_file.name}, пропускаем.")
                     except Exception as e:
                         logger.error(f"Ошибка при обработке архива {archive_file.name}: {e}", exc_info=True)
            else:
                 logger.info(f"Директория архивов {archive_dir} не найдена, пропускаем.")

            if not records_to_insert:
                logger.info("Не найдено данных активности для миграции.")
                return

            # 3. Вставка в БД
            async with aiosqlite.connect(self.db_path) as db:
                # Используем INSERT OR IGNORE, так как месячные данные не должны суммироваться при повторной миграции
                await db.executemany("""
                    INSERT OR IGNORE INTO monthly_activity (discord_user_id, game_name, year, month, total_seconds_in_month)
                    VALUES (?, ?, ?, ?, ?)
                """, records_to_insert)
                await db.commit()
                total_records_migrated = len(records_to_insert) # Приблизительно

            logger.info(f"Миграция данных активности завершена. Добавлено/проигнорировано ~{total_records_migrated} записей.")

            # 4. Обработка user_activities.json (добавление к текущему месяцу)
            daily_file = data_dir / "user_activities.json"
            if daily_file.exists() and daily_file.stat().st_size > 0:
                logger.info(f"Добавление данных из {daily_file} к текущему месяцу...")
                daily_records_to_update: List[Tuple[int, str, int, int, int]] = []
                try:
                    current_year = datetime.now().year
                    current_month = datetime.now().month
                    with open(daily_file, "r", encoding="utf-8") as f:
                        data = sync_json.load(f)
                    if isinstance(data, dict):
                         for user_id_str, games in data.items():
                            try:
                                user_id = int(user_id_str)
                                if isinstance(games, dict):
                                    for game_name, seconds in games.items():
                                        if isinstance(seconds, int) and seconds > 0:
                                            daily_records_to_update.append((user_id, game_name, current_year, current_month, seconds))
                            except ValueError:
                                 logger.warning(f"Некорректный user_id '{user_id_str}' в {daily_file}")
                    else:
                         logger.warning(f"Некорректный формат данных в {daily_file}")

                    if daily_records_to_update:
                         async with aiosqlite.connect(self.db_path) as db:
                             # Используем ON CONFLICT DO UPDATE для добавления времени
                             await db.executemany("""
                                INSERT INTO monthly_activity (discord_user_id, game_name, year, month, total_seconds_in_month)
                                VALUES (?, ?, ?, ?, ?)
                                ON CONFLICT(discord_user_id, game_name, year, month) DO UPDATE SET
                                total_seconds_in_month = total_seconds_in_month + excluded.total_seconds_in_month;
                             """, daily_records_to_update)
                             await db.commit()
                         logger.info(f"Данные из {daily_file} добавлены к monthly_activity.")

                except Exception as e:
                    logger.error(f"Ошибка при обработке {daily_file}: {e}", exc_info=True)
            else:
                 logger.info(f"{daily_file} не найден или пуст, пропускаем.")


        except Exception as e:
            logger.error(f"Критическая ошибка во время миграции данных активности: {e}", exc_info=True)

# --- Конец методов для миграции ---
