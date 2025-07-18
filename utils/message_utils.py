"""Утилиты для обработки сообщений Discord.

Этот модуль предоставляет функциональность для обработки входящих сообщений Discord,
включая настраиваемые случайные реакции на сообщения определенных пользователей.
"""

import logging
import random

import discord

from config import get_settings

logger = logging.getLogger("bot.utils.message_utils")


async def handle_message(message: discord.Message) -> None:
    """Основная логика обработки входящих сообщений (вызывается из MessageHandler).

    Проверяет, есть ли настроенные случайные реакции для автора сообщения,
    и с определенной вероятностью отправляет ответ.

    Args:
        message: Объект сообщения discord.Message.
    """
    user_id = message.author.id
    settings = get_settings()
    user_reactions = settings.reactions.user_reactions

    # Проверяем, настроены ли реакции для этого пользователя
    if user_id in user_reactions:
        reactions = user_reactions[user_id]
        for reaction in reactions:
            if random.random() < reaction.chance:
                try:
                    await message.channel.send(reaction.response)
                except discord.HTTPException as e:
                    logger.error(f"Не удалось отправить реакцию для пользователя {user_id}: {e}")
                break  # Отправляем только одну реакцию за раз
