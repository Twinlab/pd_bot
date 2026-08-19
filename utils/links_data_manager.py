"""
Модуль для управления привязками Steam ID к Discord ID пользователей.

Этот модуль предоставляет класс LinksDataManager для работы с базой данных,
хранящей информацию о привязках Steam ID к Discord ID пользователей.
Использует Tortoise ORM.
"""

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import cast

from .models import Link

logger = logging.getLogger("bot.utils.links_data_manager")


class LinksDataManager:
    """
    Управляет привязками Steam ID к Discord ID пользователей с использованием Tortoise ORM.
    """

    def __init__(self) -> None:
        """Инициализирует менеджер данных привязок."""
        logger.info("Инициализация LinksDataManager (Tortoise ORM)")

    @staticmethod
    def _load_json_file(json_file_path: str) -> object | None:
        """Синхронно читает JSON; вызывается через ``asyncio.to_thread``."""
        path = Path(json_file_path)
        if not path.is_file() or path.stat().st_size == 0:
            return None
        with path.open(encoding="utf-8") as file:
            return cast(object, json.load(file))

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
            # get_or_create возвращает кортеж (объект, создан_ли)
            _, created = await Link.get_or_create(
                discord_user_id=discord_user_id, steam_id=steam_id
            )
            if created:
                logger.info(f"Добавлена привязка для {discord_user_id}: {steam_id}")
                return True
            else:
                logger.info(f"Привязка для {discord_user_id}: {steam_id} уже существует.")
                return False
        except Exception as e:
            logger.error(
                f"Ошибка при добавлении привязки для {discord_user_id}: {e}", exc_info=True
            )
            return False

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
            deleted_count = await Link.filter(
                discord_user_id=discord_user_id, steam_id=steam_id
            ).delete()
            if deleted_count > 0:
                logger.info(f"Удалена привязка для {discord_user_id}: {steam_id}")
                return True
            else:
                logger.warning(f"Привязка для удаления не найдена: {discord_user_id} - {steam_id}")
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
            Количество удаленных привязок.
        """
        try:
            deleted_count = await Link.filter(discord_user_id=discord_user_id).delete()
            logger.info(f"Удалено {deleted_count} привязок для {discord_user_id}")
            return deleted_count
        except Exception as e:
            logger.error(
                f"Ошибка при удалении всех привязок для {discord_user_id}: {e}", exc_info=True
            )
            return 0

    async def get_links(self, discord_user_id: int) -> list[int]:
        """
        Получает список Steam ID, привязанных к Discord ID.

        Args:
            discord_user_id: ID пользователя Discord.

        Returns:
            Список Steam ID, привязанных к указанному Discord ID.
        """
        try:
            # values_list(..., flat=True) возвращает плоский список значений,
            # но Tortoise type-stubs декларируют list[tuple[Any, ...]] — приходится cast.
            links = await Link.filter(discord_user_id=discord_user_id).values_list(
                "steam_id", flat=True
            )
            logger.debug(f"Загружено {len(links)} привязок для {discord_user_id}")
            return cast(list[int], links)
        except Exception as e:
            logger.error(f"Ошибка при получении привязок для {discord_user_id}: {e}", exc_info=True)
            return []

    async def get_all_links_data(self) -> dict[int, list[int]]:
        """
        Загружает все данные о привязках из БД.

        Returns:
            Словарь, где ключи - Discord ID пользователей, значения - списки привязанных Steam ID.
        """
        all_links: dict[int, list[int]] = defaultdict(list)
        try:
            # Получаем все записи
            links = await Link.all()
            for link in links:
                all_links[link.discord_user_id].append(link.steam_id)
            logger.info(f"Загружены все данные о привязках из БД: {len(all_links)} пользователей.")
            return dict(all_links)
        except Exception as e:
            logger.error(f"Ошибка при получении всех данных о привязках: {e}", exc_info=True)
            return {}

    async def migrate_links_from_json(self, json_file_path: str = "data/user_links.json") -> int:
        """
        Мигрирует данные о привязках из JSON в базу данных.

        Args:
            json_file_path: Путь к JSON-файлу с данными о привязках.

        Returns:
            Количество успешно мигрированных привязок.
        """
        logger.info(f"Начало миграции привязок из {json_file_path}...")
        inserted_count = 0
        try:
            data = await asyncio.to_thread(self._load_json_file, json_file_path)
            if data is None:
                logger.warning(
                    f"Файл {json_file_path} не найден или пуст. Миграция привязок пропущена."
                )
                return 0

            links_to_insert: list[Link] = []

            # Вспомогательная функция для добавления в список на вставку
            def add_to_list(uid: int, sid: int) -> None:
                links_to_insert.append(Link(discord_user_id=uid, steam_id=sid))

            if isinstance(data, dict):  # Новый формат
                for user_id_str, steam_ids in data.items():
                    try:
                        user_id = int(user_id_str)
                        if isinstance(steam_ids, list):
                            for steam_id in steam_ids:
                                try:
                                    add_to_list(user_id, int(steam_id))
                                except (ValueError, TypeError):
                                    pass
                    except ValueError:
                        pass
            elif isinstance(data, list):  # Старый формат
                for item in data:
                    if isinstance(item, dict) and "user" in item and "links" in item:
                        try:
                            user_id = int(item["user"])
                            if isinstance(item["links"], list):
                                for steam_id in item["links"]:
                                    try:
                                        add_to_list(user_id, int(steam_id))
                                    except (ValueError, TypeError):
                                        pass
                        except (ValueError, TypeError):
                            pass

            if not links_to_insert:
                logger.info("Не найдено привязок для миграции.")
                return 0

            # Используем bulk_create с ignore_conflicts=True (аналог INSERT OR IGNORE)
            await Link.bulk_create(links_to_insert, ignore_conflicts=True)

            # Tortoise ORM не возвращает количество вставленных записей при bulk_create с ignore_conflicts
            # Поэтому просто вернем количество попыток вставки
            inserted_count = len(links_to_insert)

            logger.info(f"Миграция привязок завершена. Обработано {inserted_count} записей.")
            return inserted_count

        except Exception as e:
            logger.error(f"Ошибка во время миграции привязок: {e}", exc_info=True)
            return 0
