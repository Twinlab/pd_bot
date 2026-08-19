"""
Модуль для управления привязками эмодзи к ролям Discord.

Этот модуль предоставляет класс RoleReactionDataManager для работы с базой данных,
хранящей информацию о привязках эмодзи к ролям для системы ролей по реакциям.
Использует Tortoise ORM.
"""

import logging
from typing import Any, cast

from .models import RoleReaction

logger = logging.getLogger("bot.utils.role_reaction_data_manager")


class RoleReactionDataManager:
    """
    Управляет привязками эмодзи к ролям для системы ролей по реакциям с использованием Tortoise ORM.
    """

    def __init__(self) -> None:
        """Инициализирует менеджер данных привязок эмодзи к ролям."""
        logger.info("Инициализация RoleReactionDataManager (Tortoise ORM)")

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
            # Берем первую попавшуюся запись для этого сервера, так как предполагается,
            # что сообщение одно на сервер (или логика подразумевает это).
            # В оригинале было LIMIT 1.
            reaction = await RoleReaction.filter(guild_id=guild_id).first()
            if reaction:
                return reaction.channel_id, reaction.message_id
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
            # update_or_create использует уникальные поля для поиска
            # В модели RoleReaction unique_together = (("guild_id", "message_id", "emoji"),)
            await RoleReaction.update_or_create(
                guild_id=guild_id,
                message_id=message_id,
                emoji=emoji,
                defaults={
                    "channel_id": channel_id,
                    "role_id": role_id,
                    "description": description,
                },
            )
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
            deleted_count = await RoleReaction.filter(guild_id=guild_id, emoji=emoji).delete()
            if deleted_count > 0:
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
            reactions = await RoleReaction.filter(guild_id=guild_id).order_by("message_id", "emoji")
            for row in reactions:
                result.append(
                    {
                        "channel_id": row.channel_id,
                        "message_id": row.message_id,
                        "emoji": row.emoji,
                        "role_id": row.role_id,
                        "description": row.description,
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
            reaction = await RoleReaction.get_or_none(guild_id=guild_id, emoji=emoji)
            if reaction:
                return cast(int, reaction.role_id)
            return None
        except Exception as e:
            logger.error(
                f"Ошибка при получении роли для эмодзи {emoji} на сервере {guild_id}: {e}",
                exc_info=True,
            )
            return None
