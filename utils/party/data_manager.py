"""Тонкий слой над Tortoise ORM для блок-листа команды /party.

Хранит пользователей, которым админ запретил вызывать ``/party``. Управляется
через слэш-команды ``/party_block`` и ``/party_unblock`` в коге Party.
"""

import logging

from utils.models import PartyBlock

logger = logging.getLogger("bot.utils.party_data_manager")


class PartyDataManager:
    """CRUD-обёртка для модели :class:`PartyBlock`."""

    async def add_block(self, user_id: int, blocked_by: int, reason: str | None = None) -> bool:
        """Добавляет (или обновляет) блокировку пользователя.

        Args:
            user_id: Discord ID юзера, которого блокируем.
            blocked_by: Discord ID админа-инициатора.
            reason: Опциональный комментарий.

        Returns:
            True при успешной записи в БД, False при ошибке.
        """
        try:
            await PartyBlock.update_or_create(
                user_id=user_id,
                defaults={"blocked_by": blocked_by, "reason": reason},
            )
            logger.info(f"Пользователь {user_id} добавлен в blacklist /party (by {blocked_by})")
            return True
        except Exception as e:
            logger.error(f"Не удалось заблокировать {user_id}: {e}", exc_info=True)
            return False

    async def remove_block(self, user_id: int) -> bool:
        """Снимает блокировку.

        Returns:
            True если запись удалена, False если её не было или произошла ошибка.
        """
        try:
            deleted = await PartyBlock.filter(user_id=user_id).delete()
            if deleted:
                logger.info(f"Пользователь {user_id} удалён из blacklist /party")
                return True
            return False
        except Exception as e:
            logger.error(f"Не удалось разблокировать {user_id}: {e}", exc_info=True)
            return False

    async def is_blocked(self, user_id: int) -> bool:
        """Проверяет, заблокирован ли пользователь."""
        try:
            return await PartyBlock.filter(user_id=user_id).exists()
        except Exception as e:
            logger.error(f"Ошибка при проверке блокировки {user_id}: {e}", exc_info=True)
            return False

    async def list_blocks(self) -> list[dict[str, object]]:
        """Возвращает все активные блокировки.

        Returns:
            Список словарей с ключами ``user_id``, ``blocked_by``, ``reason``,
            ``created_at``. Пустой список при ошибке.
        """
        try:
            rows = await PartyBlock.all().order_by("created_at")
            return [
                {
                    "user_id": row.user_id,
                    "blocked_by": row.blocked_by,
                    "reason": row.reason,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Не удалось получить blacklist /party: {e}", exc_info=True)
            return []
