# utils/avatar_utils.py
import discord
import logging
from typing import Optional

logger = logging.getLogger("bot")

async def display_avatar(ctx, mentioned_user: Optional[discord.Member] = None):
    """
    Показывает аватар указанного пользователя или автора команды.
    
    Args:
        ctx: Контекст команды
        mentioned_user: Пользователь, чей аватар нужно показать
    """
    try:
        # Если пользователь не указан, используем автора команды
        if not mentioned_user:
            mentioned_user = ctx.author

        # Получаем аватары в более высоком качестве
        server_avatar = mentioned_user.display_avatar.with_size(1024).url
        global_avatar = mentioned_user.avatar.with_size(1024).url if mentioned_user.avatar else mentioned_user.default_avatar.with_size(1024).url

        # Создаем embed с улучшенным описанием
        embed = discord.Embed(title=f"Аватар пользователя {mentioned_user.display_name}", color=discord.Color.blue())
        embed.set_image(url=server_avatar)
        embed.description = (
            f"[Серверный аватар]({server_avatar}) | "
            f"[Глобальный аватар]({global_avatar})"
        )

        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Ошибка при отображении аватара: {e}", exc_info=True)
        await ctx.send(f"Произошла ошибка при отображении аватара: {e}")