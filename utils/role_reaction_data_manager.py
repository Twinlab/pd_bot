import aiosqlite
import logging
from typing import List, Dict, Optional, Tuple, Any
import discord

# Импортируем путь к БД из database.py
from .database import DB_PATH

logger = logging.getLogger("bot.role_reactions")

class RoleReactionDataManager:
    """
    Управляет привязками эмодзи к ролям для системы ролей по реакциям.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        logger.info(f"Инициализация RoleReactionDataManager с БД: {self.db_path}")
        
    async def get_message_info(self, guild_id: int) -> Optional[Tuple[int, int]]:
        """
        Получает информацию о сообщении с реакциями для указанного сервера.
        Возвращает (channel_id, message_id) или None, если сообщение не найдено.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT channel_id, message_id FROM role_reactions WHERE guild_id = ? LIMIT 1", 
                    (guild_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return row[0], row[1]
                    return None
        except Exception as e:
            logger.error(f"Ошибка при получении информации о сообщении для сервера {guild_id}: {e}", exc_info=True)
            return None
    
    async def add_role_reaction(self, guild_id: int, channel_id: int, message_id: int, 
                               emoji: str, role_id: int, description: str) -> bool:
        """
        Добавляет новую привязку эмодзи к роли.
        Возвращает True, если добавлено успешно, False в случае ошибки.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO role_reactions 
                    (guild_id, channel_id, message_id, emoji, role_id, description) 
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (guild_id, channel_id, message_id, emoji, role_id, description))
                await db.commit()
                logger.info(f"Добавлена привязка роли {role_id} к эмодзи {emoji} для сообщения {message_id}")
                return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении привязки роли: {e}", exc_info=True)
            return False
    
    async def remove_role_reaction(self, guild_id: int, emoji: str) -> bool:
        """
        Удаляет привязку эмодзи к роли.
        Возвращает True, если удалено успешно, False в случае ошибки или если привязка не найдена.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM role_reactions WHERE guild_id = ? AND emoji = ?", 
                    (guild_id, emoji)
                )
                await db.commit()
                if cursor.rowcount > 0:
                    logger.info(f"Удалена привязка для эмодзи {emoji} на сервере {guild_id}")
                    return True
                else:
                    logger.warning(f"Привязка для удаления не найдена: сервер {guild_id}, эмодзи {emoji}")
                    return False
        except Exception as e:
            logger.error(f"Ошибка при удалении привязки роли: {e}", exc_info=True)
            return False
    
    async def get_all_role_reactions(self, guild_id: int) -> List[Dict[str, Any]]:
        """
        Получает все привязки эмодзи к ролям для указанного сервера.
        Возвращает список словарей с информацией о привязках.
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
                    (guild_id,)
                ) as cursor:
                    async for row in cursor:
                        result.append({
                            'channel_id': row['channel_id'],
                            'message_id': row['message_id'],
                            'emoji': row['emoji'],
                            'role_id': row['role_id'],
                            'description': row['description']
                        })
            logger.debug(f"Загружено {len(result)} привязок ролей для сервера {guild_id}")
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении привязок ролей для сервера {guild_id}: {e}", exc_info=True)
            return []
    
    async def get_role_by_emoji(self, guild_id: int, emoji: str) -> Optional[int]:
        """
        Получает ID роли, привязанной к указанному эмодзи на сервере.
        Возвращает ID роли или None, если привязка не найдена.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT role_id FROM role_reactions WHERE guild_id = ? AND emoji = ?", 
                    (guild_id, emoji)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return row[0]
                    return None
        except Exception as e:
            logger.error(f"Ошибка при получении роли для эмодзи {emoji} на сервере {guild_id}: {e}", exc_info=True)
            return None
    
    async def update_message_content(self, guild_id: int, message_content: str) -> bool:
        """
        Обновляет содержимое сообщения с реакциями.
        Эта функция не используется для хранения данных в БД, но может быть полезна для кеширования.
        """
        # В текущей реализации мы не храним содержимое сообщения в БД,
        # но эта функция может быть расширена в будущем, если потребуется.
        # Сейчас просто возвращаем True для совместимости.
        return True
