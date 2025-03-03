# handlers/message_handler.py
import discord
from discord.ext import commands
import logging
import asyncio
import random
from typing import Dict, Set, Optional, List, Union

logger = logging.getLogger("bot")

class MessageHandler(commands.Cog):
    """Обработчик сообщений и реакций пользователей"""
    
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns: Dict[int, float] = {}  # ID пользователя -> время последней обработки
        logger.info(f"Ког {self.__class__.__name__} загружен")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Обрабатывает входящие сообщения пользователей"""
        # Пропускаем сообщения ботов, личные сообщения и сообщения-команды
        if (message.author.bot or 
            not message.guild or 
            message.content.startswith(self.bot.command_prefix)):
            return
        
        # Проверка кулдауна для предотвращения спама
        author_id = message.author.id
        current_time = asyncio.get_event_loop().time()
        
        # Кулдаун 2 секунды между обработками сообщений одного пользователя
        if author_id in self.cooldowns and current_time - self.cooldowns[author_id] < 2:
            return
            
        # Обновляем время последней обработки
        self.cooldowns[author_id] = current_time
            
        # Используем функцию из message_utils для обработки сообщения
        try:
            # Импортируем здесь, чтобы избежать циклических импортов
            from utils.message_utils import handle_message
            await handle_message(message)
        except ImportError:
            # Если модуль не найден, используем встроенную обработку
            await self._default_message_handler(message)
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
    
    async def _default_message_handler(self, message):
        """Базовая обработка сообщений, если модуль message_utils не найден"""
        # Специальные реакции на определенных пользователей
        reactions = {
            154601435990982656: {"chance": 0.05, "response": "иди нахуй абасранер"},
            305650048904200202: {"chance": 0.00001, "response": "деус, не клоуничай"},
            138053844167950347: {"chance": 0.00001, "response": "🎤🐀"},
            159347749991481344: [
                {"chance": 0.00001, "response": "админ хуесос"},
                {"chance": 0.00001, "response": "мин яратам өчпочмак"}
            ]
        }
        
        # Проверяем, есть ли реакции для этого пользователя
        user_id = message.author.id
        if user_id in reactions:
            reaction_data = reactions[user_id]
            
            # Обрабатываем одиночную реакцию
            if isinstance(reaction_data, dict):
                if random.random() < reaction_data["chance"]:
                    await message.channel.send(reaction_data["response"])
            
            # Обрабатываем множественные реакции
            elif isinstance(reaction_data, list):
                for reaction in reaction_data:
                    if random.random() < reaction["chance"]:
                        await message.channel.send(reaction["response"])
                        break  # Отправляем только одну реакцию за раз

async def setup(bot):
    await bot.add_cog(MessageHandler(bot))