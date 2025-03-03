import discord
from discord.ext import commands

async def clear_messages(ctx, count: int = 10, user: discord.Member = None):
    """
    Очищает сообщения в канале и возвращает их количество.
    
    Args:
        ctx: Контекст команды
        count: Количество сообщений для удаления (по умолчанию 10)
        user: Если указан, удаляются только сообщения этого пользователя
        
    Returns:
        int: Количество удаленных сообщений
    """
    def check(msg):
        if user is None:
            return True
        else:
            return msg.author == user

    # Удаляем сообщения и получаем их количество
    deleted = await ctx.channel.purge(limit=count, check=check, bulk=True)
    return len(deleted)