# utils/penis_utils.py
import random
import discord
import logging

logger = logging.getLogger("bot")

async def measure_penis(ctx):
    """
    Генерирует случайный размер пениса и отправляет его в виде эмбеда.
    
    Args:
        ctx: Контекст команды
    """
    try:
        user = ctx.author
        penis_length = random.randint(0, 15)
        penis_representation = "8" + "=" * penis_length + "D"
        
        # Определяем цвет в зависимости от размера
        if penis_length >= 10:
            color = discord.Color.green()
        elif penis_length >= 5:
            color = discord.Color.gold()
        else:
            color = discord.Color.red()

        embed = discord.Embed(
            title="Измеритель пениса",
            description=f"{user.mention}, твой пенис\n{penis_representation}",
            color=color
        )
        
        embed.add_field(name="Длина", value=f"{penis_length} см", inline=True)
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Ошибка при измерении пениса: {e}", exc_info=True)
        await ctx.send(f"Произошла ошибка при измерении: {e}")