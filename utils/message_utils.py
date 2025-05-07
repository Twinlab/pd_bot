import discord
import random
import logging
from typing import Dict, List, Union, Tuple, Optional

logger = logging.getLogger("bot")

# Словарь для настройки случайных ответов на сообщения определенных пользователей.
# Формат: {user_id: {"chance": float, "response": str}} или {user_id: [{"chance": float, "response": str}, ...]}
USER_REACTIONS = {
    154601435990982656: {"chance": 0.05, "response": "иди нахуй абасранер"},
    305650048904200202: {"chance": 0.0001, "response": "деус, не клоуничай"},
    138053844167950347: {"chance": 0.0001, "response": "🎤🐀"},
    159347749991481344: {"chance": 0.0001, "response": "админ хуесос"},
    245874719855738880: {"chance": 0.0001, "response": "мин яратам өчпочмак"}
}

async def handle_message(message: discord.Message):
    """
    Основная логика обработки входящих сообщений (вызывается из MessageHandler).
    Проверяет, есть ли настроенные случайные реакции для автора сообщения,
    и с определенной вероятностью отправляет ответ.

    Args:
        message: Объект сообщения discord.Message.
    """
    user_id = message.author.id
        
    # Проверяем, настроены ли реакции для этого пользователя
    if user_id in USER_REACTIONS:
        reaction_data = USER_REACTIONS[user_id]
            
        # Обработка случая с одной возможной реакцией
        if isinstance(reaction_data, dict):
            if random.random() < reaction_data["chance"]:
                await message.channel.send(reaction_data["response"])
            
        # Обработка случая с несколькими возможными реакциями (список словарей)
        elif isinstance(reaction_data, list):
            for reaction in reaction_data:
                if random.random() < reaction["chance"]:
                    await message.channel.send(reaction["response"])
                    break  # Отправляем только одну реакцию за раз
        
    # TODO: Сюда можно добавить другую логику обработки сообщений,
    # например, реакции на ключевые слова, автоответы и т.д.
