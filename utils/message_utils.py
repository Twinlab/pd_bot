# utils/message_utils.py
import discord
import random
import logging
from typing import Dict, List, Union, Tuple, Optional

logger = logging.getLogger("bot")

# Настройки случайных ответов на сообщения определенных пользователей
USER_REACTIONS = {
    154601435990982656: {"chance": 0.05, "response": "иди нахуй абасранер"},
    305650048904200202: {"chance": 0.0001, "response": "деус, не клоуничай"},
    138053844167950347: {"chance": 0.0001, "response": "🎤🐀"},
    159347749991481344: {"chance": 0.0001, "response": "админ хуесос"},
    245874719855738880: {"chance": 0.0001, "response": "мин яратам өчпочмак"}
}

async def handle_message(message: discord.Message):
    """
    Обрабатывает входящие сообщения с различными реакциями и ответами.
    
    Args:
        message: Объект сообщения Discord
    """
    try:
        user_id = message.author.id
        
        # Проверяем специальные реакции для конкретного пользователя
        if user_id in USER_REACTIONS:
            reaction_data = USER_REACTIONS[user_id]
            
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
        
        # Здесь можно добавить другие обработчики сообщений
        # Например, реакции на определенные ключевые слова
            
    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}", exc_info=True)



