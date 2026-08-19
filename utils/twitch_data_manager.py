"""Менеджер данных для отслеживания Twitch-стримеров с использованием Tortoise ORM."""

import logging
import time
from typing import Any

from .models import TwitchStreamer

logger = logging.getLogger("bot.utils.twitch_data_manager")


class TwitchDataManager:
    """
    Управляет данными о Twitch-стримерах с использованием Tortoise ORM.

    Этот класс предоставляет методы для работы с данными о Twitch-стримерах,
    включая добавление, удаление, получение и обновление информации о стримерах.
    """

    def __init__(self) -> None:
        """Инициализирует менеджер данных Twitch."""
        logger.info("Инициализация TwitchDataManager (Tortoise ORM)")

    async def add_streamer(
        self, guild_id: int, channel_id: int, twitch_username: str, twitch_id: str | None = None
    ) -> bool:
        """
        Добавляет стримера для отслеживания или обновляет существующего.

        Args:
            guild_id: ID сервера Discord
            channel_id: ID канала для отправки уведомлений
            twitch_username: Имя пользователя Twitch (без учета регистра)
            twitch_id: ID пользователя Twitch (опционально, может быть получен позже)

        Returns:
            bool: True если добавлено или обновлено успешно, False в случае ошибки
        """
        try:
            twitch_username = twitch_username.lower()

            # update_or_create использует уникальные поля для поиска
            # В модели TwitchStreamer unique_together = (("guild_id", "twitch_username"),)
            await TwitchStreamer.update_or_create(
                guild_id=guild_id,
                twitch_username=twitch_username,
                defaults={
                    "channel_id": channel_id,
                    "twitch_id": twitch_id,
                    # is_live и last_notification_time не обновляем при добавлении/обновлении канала
                },
            )
            logger.info(f"Добавлен/обновлен стример {twitch_username} для сервера {guild_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении стримера {twitch_username}: {e}", exc_info=True)
            return False

    async def remove_streamer(self, guild_id: int, twitch_username: str) -> bool:
        """
        Удаляет стримера из отслеживаемых для конкретного сервера.

        Args:
            guild_id: ID сервера Discord
            twitch_username: Имя пользователя Twitch (без учета регистра)

        Returns:
            bool: True если удалено, False если не найдено или произошла ошибка
        """
        try:
            twitch_username = twitch_username.lower()
            deleted_count = await TwitchStreamer.filter(
                guild_id=guild_id, twitch_username=twitch_username
            ).delete()

            if deleted_count > 0:
                logger.info(f"Удален стример {twitch_username}")
                return True
            else:
                logger.warning(f"Стример {twitch_username} не найден")
                return False
        except Exception as e:
            logger.error(f"Ошибка при удалении стримера {twitch_username}: {e}", exc_info=True)
            return False

    async def get_streamers(self, guild_id: int) -> list[dict]:
        """
        Получает список всех отслеживаемых стримеров для конкретного сервера.

        Args:
            guild_id: ID сервера Discord

        Returns:
            list[dict]: Список словарей с информацией о стримерах.
        """
        streamers = []
        try:
            # Получаем объекты моделей
            streamer_objs = await TwitchStreamer.filter(guild_id=guild_id)
            for obj in streamer_objs:
                streamers.append(
                    {
                        "guild_id": obj.guild_id,
                        "channel_id": obj.channel_id,
                        "twitch_username": obj.twitch_username,
                        "twitch_id": obj.twitch_id,
                        "is_live": obj.is_live,
                        "last_stream_id": obj.last_stream_id,
                        "last_notification_time": obj.last_notification_time,
                    }
                )

            logger.debug(f"Получено {len(streamers)} стримеров")
            return streamers
        except Exception as e:
            logger.error(f"Ошибка при получении стримеров: {e}", exc_info=True)
            return []

    async def update_streamer_status(
        self,
        twitch_username: str,
        guild_id: int,
        is_live: bool,
        stream_id: str | None = None,
    ) -> bool:
        """
        Обновляет статус стримера (онлайн/оффлайн) и ID стрима.

        Args:
            twitch_username: Имя пользователя Twitch (без учета регистра)
            guild_id: ID единственного сервера Discord.
            is_live: True если стример онлайн, False если оффлайн
            stream_id: ID текущего стрима (используется только если is_live=True)

        Returns:
            bool: True если обновлено успешно, False в случае ошибки
        """
        try:
            twitch_username = twitch_username.lower()

            update_data: dict[str, Any] = {"is_live": is_live}
            if is_live and stream_id is not None:
                update_data["last_stream_id"] = stream_id

            await TwitchStreamer.filter(
                twitch_username=twitch_username,
                guild_id=guild_id,
            ).update(**update_data)

            logger.debug(
                f"Обновлен статус стримера {twitch_username}: {'онлайн' if is_live else 'оффлайн'}"
            )
            return True
        except Exception as e:
            logger.error(
                f"Ошибка при обновлении статуса стримера {twitch_username}: {e}", exc_info=True
            )
            return False

    async def update_notification_time(
        self, twitch_username: str, guild_id: int, stream_id: str | None = None
    ) -> bool:
        """
        Обновляет время последнего уведомления о стриме и ID стрима для конкретного сервера.

        Args:
            twitch_username: Имя пользователя Twitch (без учета регистра)
            guild_id: ID сервера Discord
            stream_id: ID текущего стрима (если не указан, обновляется только время)

        Returns:
            bool: True если обновлено успешно, False в случае ошибки
        """
        try:
            twitch_username = twitch_username.lower()
            current_time = int(time.time())

            update_data: dict[str, Any] = {"last_notification_time": current_time}
            if stream_id:
                update_data["last_stream_id"] = stream_id

            await TwitchStreamer.filter(twitch_username=twitch_username, guild_id=guild_id).update(
                **update_data
            )

            if stream_id:
                logger.debug(
                    f"Обновлено время уведомления и ID стрима ({stream_id}) "
                    f"для стримера {twitch_username}"
                )
            else:
                logger.debug(f"Обновлено время уведомления для стримера {twitch_username}")
            return True
        except Exception as e:
            logger.error(
                f"Ошибка при обновлении времени уведомления для {twitch_username}: {e}",
                exc_info=True,
            )
            return False

    async def update_twitch_id(self, twitch_username: str, guild_id: int, twitch_id: str) -> bool:
        """
        Обновляет Twitch ID для стримера.

        Args:
            twitch_username: Имя пользователя Twitch (без учета регистра)
            guild_id: ID единственного сервера Discord.
            twitch_id: ID пользователя Twitch

        Returns:
            bool: True если обновлено успешно, False в случае ошибки
        """
        try:
            twitch_username = twitch_username.lower()
            await TwitchStreamer.filter(
                twitch_username=twitch_username,
                guild_id=guild_id,
            ).update(twitch_id=twitch_id)
            logger.debug(f"Обновлен Twitch ID для стримера {twitch_username}: {twitch_id}")
            return True
        except Exception as e:
            logger.error(
                f"Ошибка при обновлении Twitch ID для {twitch_username}: {e}", exc_info=True
            )
            return False
