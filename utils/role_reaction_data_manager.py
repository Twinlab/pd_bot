"""
Модуль для управления привязками эмодзи к ролям Discord.

Этот модуль предоставляет класс RoleReactionDataManager для работы с базой данных SQLite,
хранящей информацию о привязках эмодзи к ролям для системы ролей по реакциям.
Включает функциональность для добавления, удаления и получения привязок.
"""

import logging
from typing import Any, cast

import aiosqlite

# Импортируем путь к БД из database.py
from .database import DB_PATH

logger = logging.getLogger("bot.utils.role_reaction_data_manager")


class RoleReactionDataManager:
    """
    Управляет привязками эмодзи к ролям для системы ролей по реакциям.

    Класс предоставляет асинхронные методы для добавления, удаления и получения
    привязок эмодзи к ролям Discord. Данные хранятся в таблице role_reactions
    базы данных SQLite. Каждая привязка связывает эмодзи с определенной ролью
    на конкретном сервере и сообщении.
    """

    def __init__(self, db_path: str = str(DB_PATH)) -> None:
        """
        Инициализирует менеджер данных привязок эмодзи к ролям.

        Args:
            db_path: Путь к файлу базы данных SQLite. По умолчанию используется
                     путь из модуля database.
        """
        self.db_path = db_path
        logger.info(f"Инициализация RoleReactionDataManager с БД: {self.db_path}")

    async def get_message_info(self, guild_id: int) -> tuple[int, int] | None:
        """
        Получает информацию о сообщении с реакциями для указанного сервера.

        Args:
            guild_id: ID сервера Discord.

        Returns:
            Кортеж (channel_id, message_id) или None, если сообщение не найдено
            или произошла ошибка.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT channel_id, message_id FROM role_reactions WHERE guild_id = ? LIMIT 1",
                    (guild_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return row[0], row[1]
                    return None
        except Exception as e:
            logger.error(
                f"Ошибка при получении информации о сообщении для сервера {guild_id}: {e}",
                exc_info=True,
            )
            return None

    async def add_role_reaction(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        emoji: str,
        role_id: int,
        description: str,
    ) -> bool:
        """
        Добавляет новую привязку эмодзи к роли.

        Args:
            guild_id: ID сервера Discord.
            channel_id: ID канала, где находится сообщение.
            message_id: ID сообщения, к которому привязываются реакции.
            emoji: Эмодзи для реакции (в формате Unicode или ID кастомного эмодзи).
            role_id: ID роли, которая будет выдаваться при реакции.
            description: Описание роли для отображения в сообщении.

        Returns:
            True, если привязка добавлена успешно, False в случае ошибки.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO role_reactions
                    (guild_id, channel_id, message_id, emoji, role_id, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (guild_id, channel_id, message_id, emoji, role_id, description),
                )
                await db.commit()
                logger.info(
                    f"Добавлена привязка роли {role_id} к эмодзи {emoji} для сообщения {message_id}"
                )
                return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении привязки роли: {e}", exc_info=True)
            return False

    async def remove_role_reaction(self, guild_id: int, emoji: str) -> bool:
        """
        Удаляет привязку эмодзи к роли.

        Args:
            guild_id: ID сервера Discord.
            emoji: Эмодзи, привязку которого нужно удалить.

        Returns:
            True, если привязка удалена успешно, False в случае ошибки
            или если привязка не найдена.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM role_reactions WHERE guild_id = ? AND emoji = ?", (guild_id, emoji)
                )
                await db.commit()
                if cursor.rowcount > 0:
                    logger.info(f"Удалена привязка для эмодзи {emoji} на сервере {guild_id}")
                    return True
                else:
                    logger.warning(
                        f"Привязка для удаления не найдена: сервер {guild_id}, эмодзи {emoji}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Ошибка при удалении привязки роли: {e}", exc_info=True)
            return False

    async def get_all_role_reactions(self, guild_id: int) -> list[dict[str, Any]]:
        """
        Получает все привязки эмодзи к ролям для указанного сервера.

        Args:
            guild_id: ID сервера Discord.

        Returns:
            Список словарей с информацией о привязках. Каждый словарь содержит
            ключи: 'channel_id', 'message_id', 'emoji', 'role_id', 'description'.
            Возвращает пустой список в случае ошибки или если привязки не найдены.
        """
        result = []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT channel_id, message_id, emoji, role_id, description
                       FROM role_reactions
                       WHERE guild_id = ?
                       ORDER BY message_id, emoji""",
                    (guild_id,),
                ) as cursor:
                    async for row in cursor:
                        result.append(
                            {
                                "channel_id": row["channel_id"],
                                "message_id": row["message_id"],
                                "emoji": row["emoji"],
                                "role_id": row["role_id"],
                                "description": row["description"],
                            }
                        )
            logger.debug(f"Загружено {len(result)} привязок ролей для сервера {guild_id}")
            return result
        except Exception as e:
            logger.error(
                f"Ошибка при получении привязок ролей для сервера {guild_id}: {e}", exc_info=True
            )
            return []

    async def get_role_by_emoji(self, guild_id: int, emoji: str) -> int | None:
        """
        Получает ID роли, привязанной к указанному эмодзи на сервере.

        Args:
            guild_id: ID сервера Discord.
            emoji: Эмодзи, для которого нужно найти привязанную роль.

        Returns:
            ID роли или None, если привязка не найдена или произошла ошибка.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT role_id FROM role_reactions WHERE guild_id = ? AND emoji = ?",
                    (guild_id, emoji),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return cast(int, row[0])
                    return None
        except Exception as e:
            logger.error(
                f"Ошибка при получении роли для эмодзи {emoji} на сервере {guild_id}: {e}",
                exc_info=True,
            )
            return None
