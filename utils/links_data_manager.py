"""
Модуль для управления привязками Steam ID к Discord ID пользователей.

Этот модуль предоставляет класс LinksDataManager для работы с базой данных SQLite,
хранящей информацию о привязках Steam ID к Discord ID пользователей. Включает
функциональность для добавления, удаления, получения привязок и миграции данных
из JSON-файла в базу данных SQLite.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Tuple

import aiosqlite

# Импортируем путь к БД из database.py
from .database import DB_PATH

logger = logging.getLogger("bot.utils.links_data_manager")


class LinksDataManager:
    """
    Управляет привязками Steam ID к Discord ID пользователей с использованием SQLite.

    Класс предоставляет асинхронные методы для добавления, удаления и получения
    привязок Steam ID к Discord ID пользователей. Данные хранятся в таблице links
    базы данных SQLite. Также включает функциональность для миграции данных из
    JSON-файла в базу данных.
    """

    def __init__(self, db_path: str = str(DB_PATH)) -> None:
        """
        Инициализирует менеджер данных привязок.

        Args:
            db_path: Путь к файлу базы данных SQLite. По умолчанию используется
                     путь из модуля database.
        """
        self.db_path = db_path
        logger.info(f"Инициализация LinksDataManager с БД: {self.db_path}")

    async def add_link(self, discord_user_id: int, steam_id: int) -> bool:
        """
        Добавляет привязку Steam ID к Discord ID.

        Args:
            discord_user_id: ID пользователя Discord.
            steam_id: ID аккаунта Steam.

        Returns:
            True если привязка успешно добавлена, False если привязка уже существует
            или произошла ошибка.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Пытаемся вставить, игнорируя дубликаты
                await db.execute(
                    """
                    INSERT OR IGNORE INTO links (discord_user_id, steam_id) VALUES (?, ?)
                """,
                    (discord_user_id, steam_id),
                )
                # Проверяем, была ли строка действительно вставлена
                changes = db.total_changes
                await db.commit()
                # total_changes не всегда надежен после INSERT OR IGNORE в aiosqlite
                # Лучше проверить наличие перед вставкой или использовать SELECT changes()
                # Пока оставим так для простоты, но это потенциальное улучшение
                if changes > 0:
                    logger.info(f"Добавлена привязка для {discord_user_id}: {steam_id}")
                    return True
                else:
                    # Проверим, существует ли запись, чтобы точно знать причину
                    async with db.execute(
                        "SELECT 1 FROM links WHERE discord_user_id = ? AND steam_id = ?",
                        (discord_user_id, steam_id),
                    ) as cursor:
                        exists = await cursor.fetchone()
                        if exists:
                            logger.info(
                                f"Привязка для {discord_user_id}: {steam_id} уже существует."
                            )
                        else:
                            # Если changes == 0 и записи нет,
                            # значит была ошибка, но она не перехвачена (?)
                            logger.warning(
                                (
                                    f"Не удалось добавить привязку {discord_user_id}: "
                                    f"{steam_id}, "
                                    "но она и не существовала."
                                )
                            )
                    return False  # Возвращаем False, т.к. новая запись не добавлена
        except Exception as e:
            logger.error(
                f"Ошибка при добавлении привязки для {discord_user_id}: {e}", exc_info=True
            )
            return False  # Возвращаем False при ошибке

    async def remove_link(self, discord_user_id: int, steam_id: int) -> bool:
        """
        Удаляет конкретную привязку Steam ID для Discord ID.

        Args:
            discord_user_id: ID пользователя Discord.
            steam_id: ID аккаунта Steam.

        Returns:
            True если привязка успешно удалена, False если привязка не найдена
            или произошла ошибка.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM links WHERE discord_user_id = ? AND steam_id = ?",
                    (discord_user_id, steam_id),
                )
                await db.commit()
                if cursor.rowcount > 0:  # rowcount более надежен для DELETE
                    logger.info(f"Удалена привязка для {discord_user_id}: {steam_id}")
                    return True
                else:
                    logger.warning(
                        f"Привязка для удаления не найдена: {discord_user_id} - {steam_id}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Ошибка при удалении привязки для {discord_user_id}: {e}", exc_info=True)
            return False

    async def remove_all_links(self, discord_user_id: int) -> int:
        """
        Удаляет все привязки для указанного Discord ID.

        Args:
            discord_user_id: ID пользователя Discord.

        Returns:
            Количество удаленных привязок. Возвращает 0, если привязки не найдены
            или произошла ошибка.
        """
        count = 0
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM links WHERE discord_user_id = ?", (discord_user_id,)
                )
                count = cursor.rowcount  # Используем rowcount
                await db.commit()
                logger.info(f"Удалено {count} привязок для {discord_user_id}")
                return count
        except Exception as e:
            logger.error(
                f"Ошибка при удалении всех привязок для {discord_user_id}: {e}", exc_info=True
            )
            return 0

    async def get_links(self, discord_user_id: int) -> List[int]:
        """
        Получает список Steam ID, привязанных к Discord ID.

        Args:
            discord_user_id: ID пользователя Discord.

        Returns:
            Список Steam ID, привязанных к указанному Discord ID.
            Возвращает пустой список, если привязки не найдены или произошла ошибка.
        """
        links: List[int] = []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT steam_id FROM links WHERE discord_user_id = ?", (discord_user_id,)
                ) as cursor:
                    async for row in cursor:
                        links.append(row[0])
            logger.debug(f"Загружено {len(links)} привязок для {discord_user_id}")
            return links
        except Exception as e:
            logger.error(f"Ошибка при получении привязок для {discord_user_id}: {e}", exc_info=True)
            return []

    async def get_all_links_data(self) -> Dict[int, List[int]]:
        """
        Загружает все данные о привязках из БД.

        Returns:
            Словарь, где ключи - Discord ID пользователей, значения - списки привязанных Steam ID.
            Возвращает пустой словарь, если привязки не найдены или произошла ошибка.

        Note:
            Может быть неэффективно для больших баз данных.
        """
        all_links: Dict[int, List[int]] = defaultdict(list)
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT discord_user_id, steam_id FROM links ORDER BY discord_user_id"
                ) as cursor:
                    async for row in cursor:
                        discord_id, steam_id = row
                        all_links[discord_id].append(steam_id)
            logger.info(f"Загружены все данные о привязках из БД: {len(all_links)} пользователей.")
            return dict(all_links)
        except Exception as e:
            logger.error(f"Ошибка при получении всех данных о привязках: {e}", exc_info=True)
            return {}

    # --- Метод для миграции (используется в migrate_to_sqlite.py) ---
    async def migrate_links_from_json(self, json_file_path: str = "data/user_links.json") -> int:
        """
        Мигрирует данные о привязках из JSON в SQLite.

        Args:
            json_file_path: Путь к JSON-файлу с данными о привязках.
                           По умолчанию "data/user_links.json".

        Returns:
            Количество успешно мигрированных привязок.
            Возвращает 0, если миграция не удалась или произошла ошибка.

        Note:
            Поддерживает как новый формат (словарь), так и старый формат (список) JSON-файла.
        """
        logger.info(f"Начало миграции привязок из {json_file_path}...")
        inserted_count = 0
        # Используем синхронный код для чтения JSON, так как это одноразовая операция
        try:
            import json as sync_json
            import os as sync_os

            if not sync_os.path.exists(json_file_path) or sync_os.path.getsize(json_file_path) == 0:
                logger.warning(
                    f"Файл {json_file_path} не найден или пуст. " "Миграция привязок пропущена."
                )
                return 0  # Возвращаем 0 мигрированных записей

            with open(json_file_path, "r", encoding="utf-8") as f:
                data = sync_json.load(f)

            links_to_insert: List[Tuple[int, int]] = []
            if isinstance(data, dict):  # Новый формат
                for user_id_str, steam_ids in data.items():
                    try:
                        user_id = int(user_id_str)
                        if isinstance(steam_ids, list):
                            for steam_id in steam_ids:
                                try:
                                    links_to_insert.append((user_id, int(steam_id)))
                                except (ValueError, TypeError):
                                    logger.warning(
                                        (
                                            f"Некорректный steam_id '{steam_id}' для {user_id} "
                                            f"в {json_file_path}"
                                        )
                                    )
                        else:
                            logger.warning(
                                f"Некорректный формат steam_ids для {user_id} в {json_file_path}"
                            )
                    except ValueError:
                        logger.warning(f"Некорректный user_id '{user_id_str}' в {json_file_path}")
            elif isinstance(data, list):  # Старый формат
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
                                        logger.warning(
                                            (
                                                f"Некорректный steam_id '{steam_id}' для {user_id} "
                                                f"в старом формате {json_file_path}"
                                            )
                                        )
                            else:
                                logger.warning(
                                    (
                                        f"Некорректный формат links для {user_id} "
                                        f"в старом формате {json_file_path}"
                                    )
                                )
                        except (ValueError, TypeError):
                            logger.warning(
                                (
                                    f"Некорректный user_id '{item.get('user')}' "
                                    f"в старом формате {json_file_path}"
                                )
                            )
                    else:
                        logger.warning(
                            f"Некорректный элемент в старом формате {json_file_path}: {item}"
                        )
            else:
                logger.error(
                    f"Неизвестный формат данных в {json_file_path}. " "Миграция привязок прервана."
                )
                return 0

            if not links_to_insert:
                logger.info("Не найдено привязок для миграции.")
                return 0

            async with aiosqlite.connect(self.db_path) as db:
                # Используем транзакцию для массовой вставки
                await db.execute("BEGIN")
                try:
                    cursor = await db.executemany(
                        "INSERT OR IGNORE INTO links (discord_user_id, steam_id) VALUES (?, ?)",
                        links_to_insert,
                    )
                    inserted_count = cursor.rowcount  # rowcount должен быть точнее для executemany
                    await db.commit()
                except Exception as insert_err:
                    logger.error(
                        f"Ошибка при вставке данных привязок, откатываем: {insert_err}",
                        exc_info=True,
                    )
                    await db.rollback()
                    inserted_count = 0  # Сбрасываем счетчик при ошибке

            logger.info(
                (
                    f"Миграция привязок завершена. Вставлено {inserted_count} "
                    "новых записей "
                    "(дубликаты проигнорированы)."
                )
            )
            return inserted_count

        except Exception as e:
            logger.error(f"Ошибка во время миграции привязок: {e}", exc_info=True)
            return 0  # Возвращаем 0 при ошибке
