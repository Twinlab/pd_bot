"""Модуль для управления привязками аккаунтов FACEIT (CS2) к Discord ID.

Хранит ``faceit_player_id`` (UUID) и ник для отображения, чтобы не резолвить
ник через API при каждом выводе списка. Использует Tortoise ORM.
"""

import logging

from .models import CsLink

logger = logging.getLogger("bot.utils.cs_links_data_manager")


class CsLinksDataManager:
    """Управляет привязками аккаунтов FACEIT к Discord ID пользователей."""

    async def add_link(self, discord_user_id: int, faceit_player_id: str, nickname: str) -> bool:
        """Добавляет привязку аккаунта FACEIT к Discord ID.

        Args:
            discord_user_id: ID пользователя Discord.
            faceit_player_id: UUID игрока FACEIT.
            nickname: Ник игрока FACEIT (для отображения).

        Returns:
            True если привязка добавлена, False если она уже существует или произошла ошибка.
        """
        try:
            _, created = await CsLink.get_or_create(
                discord_user_id=discord_user_id,
                faceit_player_id=faceit_player_id,
                defaults={"nickname": nickname},
            )
            if created:
                logger.info(f"Добавлена CS-привязка для {discord_user_id}: {nickname}")
                return True
            logger.info(f"CS-привязка для {discord_user_id}: {faceit_player_id} уже существует.")
            return False
        except Exception as e:
            logger.error(
                f"Ошибка при добавлении CS-привязки для {discord_user_id}: {e}", exc_info=True
            )
            return False

    async def remove_link(self, discord_user_id: int, faceit_player_id: str) -> bool:
        """Удаляет конкретную привязку FACEIT для Discord ID.

        Returns:
            True если привязка удалена, False если не найдена или произошла ошибка.
        """
        try:
            deleted_count = await CsLink.filter(
                discord_user_id=discord_user_id, faceit_player_id=faceit_player_id
            ).delete()
            if deleted_count > 0:
                logger.info(f"Удалена CS-привязка для {discord_user_id}: {faceit_player_id}")
                return True
            logger.warning(
                f"CS-привязка для удаления не найдена: {discord_user_id} - {faceit_player_id}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Ошибка при удалении CS-привязки для {discord_user_id}: {e}", exc_info=True
            )
            return False

    async def remove_all_links(self, discord_user_id: int) -> int:
        """Удаляет все CS-привязки для указанного Discord ID.

        Returns:
            Количество удалённых привязок.
        """
        try:
            deleted_count = await CsLink.filter(discord_user_id=discord_user_id).delete()
            logger.info(f"Удалено {deleted_count} CS-привязок для {discord_user_id}")
            return deleted_count
        except Exception as e:
            logger.error(
                f"Ошибка при удалении всех CS-привязок для {discord_user_id}: {e}", exc_info=True
            )
            return 0

    async def get_links(self, discord_user_id: int) -> list[CsLink]:
        """Получает список CS-привязок для Discord ID.

        Returns:
            Список объектов :class:`CsLink` (содержат ``faceit_player_id`` и ``nickname``).
        """
        try:
            links = await CsLink.filter(discord_user_id=discord_user_id)
            logger.debug(f"Загружено {len(links)} CS-привязок для {discord_user_id}")
            return links
        except Exception as e:
            logger.error(
                f"Ошибка при получении CS-привязок для {discord_user_id}: {e}", exc_info=True
            )
            return []
