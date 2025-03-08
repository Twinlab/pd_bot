
import random
import discord
import logging

logger = logging.getLogger("bot")

async def measure_penis(ctx, target_user=None):
    """
    Генерирует случайный размер пениса и отправляет его в виде эмбеда.
    
    Args:
        ctx: Контекст команды
        target_user: Пользователь, для которого генерируется размер (опционально)
    """
    try:
        # Если пользователь не указан, используем автора сообщения
        user = target_user if target_user else ctx.author
        penis_length = random.randint(0, 25)
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

        embed = discord.Embed(
            title="Измеритель пениса",
            description=description,
            color=color
        )
        
        embed.add_field(name="Длина", value=f"{penis_length} см", inline=True)
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Ошибка при измерении пениса: {e}", exc_info=True)
        await ctx.send(f"Произошла ошибка при измерении: {e}")
