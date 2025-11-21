"""Менеджер данных для отслеживания Twitch-стримеров с использованием SQLite."""

import logging
import time

import aiosqlite

# Импортируем путь к БД из database.py
from .database import DB_PATH

logger = logging.getLogger("bot.utils.twitch_data_manager")


class TwitchDataManager:
    """
    Управляет данными о Twitch-стримерах с использованием SQLite.

    Этот класс предоставляет методы для работы с данными о Twitch-стримерах,
    включая добавление, удаление, получение и обновление информации о стримерах.
    Все данные хранятся в SQLite базе данных.

    Attributes:
        db_path: Путь к файлу базы данных SQLite
    """

    db_path: str

    def __init__(self, db_path: str = str(DB_PATH)) -> None:
        """
        Инициализирует менеджер данных Twitch.

        Args:
            db_path: Путь к файлу базы данных SQLite. По умолчанию используется
                     путь из модуля database.
        """
        self.db_path = db_path
        logger.info(f"Инициализация TwitchDataManager с БД: {self.db_path}")

    async def initialize_table(self) -> bool:
        """
        Создает таблицу для хранения данных о Twitch-стримерах, если она не существует.

        Инициализирует структуру базы данных, создавая таблицу twitch_streamers
        и необходимые индексы, если они еще не существуют. Эта таблица хранит
        информацию о стримерах, их статусе и настройках уведомлений.

        Returns:
            bool: True в случае успешного создания/проверки таблицы, False в случае ошибки
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Таблица для хранения данных о стримерах
                await db.execute(
                    """
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
                """
                )
                # Индекс для быстрого поиска по имени пользователя
                await db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_twitch_streamers_username
                    ON twitch_streamers (twitch_username);
                """
                )
                await db.commit()
                logger.info("Таблица 'twitch_streamers' и индекс проверены/созданы.")
                return True
        except Exception as e:
            logger.error(f"Ошибка при инициализации таблицы twitch_streamers: {e}", exc_info=True)
            return False

    async def add_streamer(
        self, guild_id: int, channel_id: int, twitch_username: str, twitch_id: str | None = None
    ) -> bool:
        """
        Добавляет стримера для отслеживания или обновляет существующего.

        Добавляет нового стримера в базу данных для отслеживания или обновляет
        канал для уведомлений, если стример уже отслеживается на указанном сервере.
        Имя пользователя Twitch приводится к нижнему регистру для единообразия.

        Args:
            guild_id: ID сервера Discord
            channel_id: ID канала для отправки уведомлений
            twitch_username: Имя пользователя Twitch (без учета регистра)
            twitch_id: ID пользователя Twitch (опционально, может быть получен позже)

        Returns:
            bool: True если добавлено или обновлено успешно, False в случае ошибки
        """
        try:
            # Приводим имя пользователя к нижнему регистру для единообразия
            twitch_username = twitch_username.lower()

            async with aiosqlite.connect(self.db_path) as db:
                # Проверяем, существует ли уже такой стример для этого сервера
                async with db.execute(
                    "SELECT 1 FROM twitch_streamers WHERE guild_id = ? AND twitch_username = ?",
                    (guild_id, twitch_username),
                ) as cursor:
                    if await cursor.fetchone():
                        # Если стример уже существует, обновляем канал для уведомлений
                        await db.execute(
                            (
                                "UPDATE twitch_streamers SET channel_id = ? "
                                "WHERE guild_id = ? AND twitch_username = ?"
                            ),
                            (channel_id, guild_id, twitch_username),
                        )
                        await db.commit()
                        logger.info(f"Обновлен канал для стримера {twitch_username}")
                        return True

                # Добавляем нового стримера
                await db.execute(
                    """
                    INSERT INTO twitch_streamers
                    (
                        guild_id,
                        channel_id,
                        twitch_username,
                        twitch_id,
                        is_live,
                        last_notification_time
                    )
                    VALUES (?, ?, ?, ?, 0, 0)
                    """,
                    (guild_id, channel_id, twitch_username, twitch_id),
                )
                await db.commit()
                logger.info(f"Добавлен стример {twitch_username}")
                return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении стримера {twitch_username}: {e}", exc_info=True)
            return False

    async def remove_streamer(self, guild_id: int, twitch_username: str) -> bool:
        """
        Удаляет стримера из отслеживаемых для конкретного сервера.

        Удаляет запись о стримере из базы данных для указанного сервера Discord.
        Имя пользователя Twitch приводится к нижнему регистру для единообразия.
        Если стример отслеживается на нескольких серверах, удаляется только запись
        для указанного сервера.

        Args:
            guild_id: ID сервера Discord
            twitch_username: Имя пользователя Twitch (без учета регистра)

        Returns:
            bool: True если удалено, False если не найдено или произошла ошибка
        """
        try:
            # Приводим имя пользователя к нижнему регистру для единообразия
            twitch_username = twitch_username.lower()

            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM twitch_streamers WHERE guild_id = ? AND twitch_username = ?",
                    (guild_id, twitch_username),
                )
                await db.commit()

                if cursor.rowcount > 0:
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

        Извлекает из базы данных информацию о всех стримерах, которые отслеживаются
        на указанном сервере Discord. Каждый стример представлен в виде словаря
        с полями: guild_id, channel_id, twitch_username, twitch_id, is_live,
        last_stream_id, last_notification_time.

        Args:
            guild_id: ID сервера Discord

        Returns:
            List[Dict]: Список словарей с информацией о стримерах. Пустой список,
                если стримеры не найдены или произошла ошибка.
        """
        streamers = []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT guild_id, channel_id, twitch_username, twitch_id, is_live,
                        last_stream_id, last_notification_time
                    FROM twitch_streamers
                    WHERE guild_id = ?
                    """,
                    (guild_id,),
                ) as cursor:
                    async for row in cursor:
                        streamers.append(dict(row))

            logger.debug(f"Получено {len(streamers)} стримеров")
            return streamers
        except Exception as e:
            logger.error(f"Ошибка при получении стримеров: {e}", exc_info=True)
            return []

    async def get_all_streamers(self) -> list[dict]:
        """
        Получает список всех отслеживаемых стримеров для всех серверов.

        Извлекает из базы данных информацию о всех стримерах, которые отслеживаются
        на всех серверах. Используется для глобальной проверки статуса стримов.
        Каждый стример представлен в виде словаря с полями: guild_id, channel_id,
        twitch_username, twitch_id, is_live, last_stream_id, last_notification_time.

        Returns:
            List[Dict]: Список словарей с информацией о стримерах. Пустой список,
                если стримеры не найдены или произошла ошибка.
        """
        streamers = []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT guild_id, channel_id, twitch_username, twitch_id, is_live,
                        last_stream_id, last_notification_time
                    FROM twitch_streamers
                    """
                ) as cursor:
                    async for row in cursor:
                        streamers.append(dict(row))

            logger.debug(f"Получено {len(streamers)} стримеров для всех серверов")
            return streamers
        except Exception as e:
            logger.error(f"Ошибка при получении всех стримеров: {e}", exc_info=True)
            return []

    async def update_streamer_status(
        self, twitch_username: str, is_live: bool, stream_id: str | None = None
    ) -> bool:
        """
        Обновляет статус стримера (онлайн/оффлайн) и ID стрима.

        Обновляет статус стримера во всех записях базы данных, где встречается
        указанное имя пользователя Twitch. Это позволяет отслеживать, когда стример
        начинает или заканчивает стрим. Если стример онлайн, устанавливается флаг is_live = 1,
        иначе is_live = 0.

        Args:
            twitch_username: Имя пользователя Twitch (без учета регистра)
            is_live: True если стример онлайн, False если оффлайн
            stream_id: ID текущего стрима (используется только если is_live=True)

        Returns:
            bool: True если обновлено успешно, False в случае ошибки
        """
        try:
            # Приводим имя пользователя к нижнему регистру для единообразия
            twitch_username = twitch_username.lower()

            async with aiosqlite.connect(self.db_path) as db:
                if is_live and stream_id:
                    # Обновляем только статус is_live, но не last_stream_id
                    # last_stream_id будет обновляться отдельно для каждого сервера
                    # при отправке уведомления через update_notification_time
                    await db.execute(
                        """
                        UPDATE twitch_streamers
                        SET is_live = 1
                        WHERE twitch_username = ?
                        """,
                        (twitch_username,),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE twitch_streamers
                        SET is_live = 0
                        WHERE twitch_username = ?
                        """,
                        (twitch_username,),
                    )

                await db.commit()
                logger.debug(

                        f"Обновлен статус стримера {twitch_username}: "
                        f"{'онлайн' if is_live else 'оффлайн'}"

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

        Этот метод вызывается после отправки уведомления о стриме на сервер Discord.
        Он обновляет время последнего уведомления (текущее время в формате UNIX timestamp)
        и, опционально, ID текущего стрима. Это позволяет избежать повторных уведомлений
        о том же стриме.

        Args:
            twitch_username: Имя пользователя Twitch (без учета регистра)
            guild_id: ID сервера Discord
            stream_id: ID текущего стрима (если не указан, обновляется только время)

        Returns:
            bool: True если обновлено успешно, False в случае ошибки
        """
        try:
            # Приводим имя пользователя к нижнему регистру для единообразия
            twitch_username = twitch_username.lower()
            current_time = int(time.time())

            async with aiosqlite.connect(self.db_path) as db:
                if stream_id:
                    # Обновляем и время уведомления, и ID стрима
                    await db.execute(
                        """
                        UPDATE twitch_streamers
                        SET last_notification_time = ?, last_stream_id = ?
                        WHERE twitch_username = ? AND guild_id = ?
                        """,
                        (current_time, stream_id, twitch_username, guild_id),
                    )
                    logger.debug(

                            f"Обновлено время уведомления и ID стрима ({stream_id}) "
                            f"для стримера {twitch_username}"

                    )
                else:
                    # Обновляем только время уведомления
                    await db.execute(
                        """
                        UPDATE twitch_streamers
                        SET last_notification_time = ?
                        WHERE twitch_username = ? AND guild_id = ?
                        """,
                        (current_time, twitch_username, guild_id),
                    )
                    logger.debug(f"Обновлено время уведомления для стримера {twitch_username}")

                await db.commit()
                return True
        except Exception as e:
            logger.error(
                f"Ошибка при обновлении времени уведомления для {twitch_username}: {e}",
                exc_info=True,
            )
            return False

    async def update_twitch_id(self, twitch_username: str, twitch_id: str) -> bool:
        """
        Обновляет Twitch ID для стримера.

        Обновляет ID пользователя Twitch для всех записей с указанным именем пользователя.
        Это необходимо, так как для работы с Twitch API требуется ID пользователя,
        а не его имя. ID может быть получен после добавления стримера в базу данных.

        Args:
            twitch_username: Имя пользователя Twitch (без учета регистра)
            twitch_id: ID пользователя Twitch

        Returns:
            bool: True если обновлено успешно, False в случае ошибки
        """
        try:
            # Приводим имя пользователя к нижнему регистру для единообразия
            twitch_username = twitch_username.lower()

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    UPDATE twitch_streamers
                    SET twitch_id = ?
                    WHERE twitch_username = ?
                    """,
                    (twitch_id, twitch_username),
                )
                await db.commit()
                logger.debug(f"Обновлен Twitch ID для стримера {twitch_username}: {twitch_id}")
                return True
        except Exception as e:
            logger.error(
                f"Ошибка при обновлении Twitch ID для {twitch_username}: {e}", exc_info=True
            )
            return False
