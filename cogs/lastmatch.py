# cogs/lastmatch.py
import discord
from discord.ext import commands
from typing import Optional
import logging

logger = logging.getLogger("bot")

# Импорт обработчика матчей из нового модуля
from utils.dota_match_utils import handle_lastmatch

class LastMatch(commands.Cog):
    """Команды для просмотра информации о последних матчах Dota 2"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен")
    
    @commands.hybrid_command(description='Показать информацию о последнем матче')
    async def lastmatch(self, ctx, member: Optional[discord.Member] = None):
        """Показывает информацию о последнем матче Dota 2"""
        # Получаем ссылку на ког Links
        links_cog = self.bot.get_cog("Links")
        if not links_cog:
            await ctx.send("Ошибка: не удалось получить данные о привязках аккаунтов.")
            return
        
        # Получаем данные о привязках
        user_links = links_cog.get_user_links()
        
        # Сообщаем Discord, что команда может выполняться дольше обычного
        await ctx.defer()
        
        # Вызываем обработчик
        await handle_lastmatch(ctx, user_links, member)

async def setup(bot):
    await bot.add_cog(LastMatch(bot))