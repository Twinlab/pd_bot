import discord
from discord.ext import commands
import logging
import asyncio
import random
from typing import Dict, Set, Optional, List, Union

logger = logging.getLogger("bot")

class MessageHandler(commands.Cog):
    """
    Ког для обработки входящих сообщений пользователей.
    Игнорирует ботов, личные сообщения и команды.
    Применяет кулдаун для предотвращения спама реакциями.
    Вызывает `utils.message_utils.handle_message` для основной логики.
    """
    def __init__(self, bot):
        """Инициализирует ког и словарь для кулдаунов."""
        self.bot = bot
        # Словарь для отслеживания времени последней обработки сообщения от пользователя {user_id: timestamp}
        self.cooldowns: Dict[int, float] = {}
        logger.info(f"Ког {self.__class__.__name__} загружен")
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Событие: вызывается при получении нового сообщения.
        Фильтрует сообщения и вызывает обработчик `handle_message`.
        """
        # Игнорируем сообщения от ботов, сообщения вне серверов (в ЛС) и команды
        if (message.author.bot or
            not message.guild or 
            message.content.startswith(self.bot.command_prefix)): # Проверяем префикс из конфига
            return
        
        # Проверка кулдауна (2 секунды) для конкретного пользователя
        author_id = message.author.id
        current_time = asyncio.get_event_loop().time()
        
        # Кулдаун 2 секунды между обработками сообщений одного пользователя
        if author_id in self.cooldowns and current_time - self.cooldowns[author_id] < 2:
            return # Игнорируем сообщение, если кулдаун активен
            
        # Обновляем время последней обработки для этого пользователя
        self.cooldowns[author_id] = current_time
            
        # Вызываем основную логику обработки сообщения из utils
        try:
            # Импорт внутри метода для избежания потенциальных циклических зависимостей при запуске
            from utils.message_utils import handle_message
            await handle_message(message)
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)

async def setup(bot):
    await bot.add_cog(MessageHandler(bot))
