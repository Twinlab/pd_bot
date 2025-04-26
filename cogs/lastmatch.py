import discord
from discord.ext import commands
from typing import Optional
import logging

# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

# Импорт обработчика матчей из нового модуля
from utils.dota_match_utils import handle_lastmatch

class LastMatch(commands.Cog):
    """Команды для просмотра информации о последних матчах Dota 2"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен")
    
    @commands.hybrid_command(description='Показать информацию о последнем матче Dota 2')
    @command_error_handler
    async def lastmatch(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """
        Показывает информацию о последнем матче Dota 2 для указанного пользователя
        (или автора команды, если пользователь не указан).
        Требует предварительной привязки Steam ID через команду /link.
        """
        # Получаем доступ к когу Links для получения привязок аккаунтов
        links_cog = self.bot.get_cog("Links")
        if not links_cog:
            await ctx.send("Ошибка: не удалось получить данные о привязках аккаунтов.")
            return
        
        # Определяем ID пользователя, для которого нужно получить ссылки
        target_user = member if member else ctx.author
        user_id = target_user.id

        # Получаем список привязанных Steam ID для этого пользователя
        user_links = await links_cog.links_manager.get_links(user_id)

        # Отмечаем взаимодействие как отложенное, т.к. запрос к API может занять время
        await ctx.defer()
        
        # Вызываем основную логику обработки команды из utils/dota_match_utils.py
        await handle_lastmatch(ctx, user_links, member)

async def setup(bot):
    await bot.add_cog(LastMatch(bot))
