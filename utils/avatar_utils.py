import discord
import logging
from typing import Optional

logger = logging.getLogger("bot")

async def display_avatar(ctx: commands.Context, mentioned_user: Optional[discord.Member] = None):
    """
    Создает и отправляет эмбед с аватаром пользователя.
    Отображает серверный аватар как основное изображение и предоставляет ссылки
    на серверный и глобальный аватары в высоком разрешении.

    Args:
        ctx: Контекст команды.
        mentioned_user: Пользователь, чей аватар нужно показать (если None, используется автор команды).
    """
    # Определяем целевого пользователя
    if not mentioned_user:
        mentioned_user = ctx.author
 
    # Получаем URL серверного и глобального аватаров в размере 1024px
    # display_avatar возвращает серверный аватар, если он есть, иначе глобальный
    server_avatar = mentioned_user.display_avatar.with_size(1024).url
    # .avatar возвращает глобальный аватар (или None), default_avatar - стандартный Discord аватар
    global_avatar = mentioned_user.avatar.with_size(1024).url if mentioned_user.avatar else mentioned_user.default_avatar.with_size(1024).url
 
    # Создаем эмбед
    embed = discord.Embed(title=f"Аватар {mentioned_user.display_name}", color=discord.Color.blue())
    embed.set_image(url=server_avatar)
    embed.description = (
        f"[Серверный аватар]({server_avatar}) | "
        f"[Глобальный аватар]({global_avatar})" # Ссылки на оба аватара
    )
 
    # Отправляем эмбед
    await ctx.send(embed=embed)
