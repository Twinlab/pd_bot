"""
Утилиты для команды измерения пениса.

Этот модуль предоставляет функциональность для генерации случайного размера пениса
и отображения результата в виде эмбеда Discord с соответствующим форматированием
и цветовой индикацией в зависимости от размера.
"""

import logging
import random

import discord
from discord.ext import commands

logger = logging.getLogger("bot.utils.penis_utils")


async def measure_penis(ctx: commands.Context, target_user: discord.Member | None = None) -> None:
    """
    Генерирует случайный размер пениса и отправляет его в виде эмбеда.

    Args:
        ctx: Контекст команды
        target_user: Пользователь, для которого генерируется размер (опционально)
    """
    try:
        # Получаем настройки
        from config.settings import get_settings

        settings = get_settings()

        # Если пользователь не указан, используем автора сообщения
        user = target_user if target_user else ctx.author
        penis_length = random.randint(settings.fun.penis.min_length, settings.fun.penis.max_length)
        penis_representation = "8" + "=" * penis_length + "D"

        # Определяем цвет в зависимости от размера
        if penis_length >= 15:
            color = discord.Color.green()
        elif penis_length >= 10:
            color = discord.Color.gold()
        else:
            color = discord.Color.red()

        # Разные сообщения в зависимости от того, кому измеряем
        if user == ctx.author:
            description = f"{user.mention}, твой пенис\n{penis_representation}"
        else:
            description = f"Пенис {user.mention}\n{penis_representation}"

        embed = discord.Embed(title="Измеритель пениса", description=description, color=color)

        embed.add_field(name="Длина", value=f"{penis_length} см", inline=True)

        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Ошибка при измерении пениса: {e}", exc_info=True)
        await ctx.send(f"Произошла ошибка при измерении: {e}")
