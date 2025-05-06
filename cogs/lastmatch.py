"""Ког для просмотра информации о последних матчах Dota 2."""
import discord
from discord.ext import commands
from typing import Optional
import logging

from utils.error_handler import command_error_handler
from utils.dota_match_utils import handle_lastmatch

logger = logging.getLogger("bot.lastmatch") # Иерархическое имя логгера

class LastMatchCog(commands.Cog):
    """Команды для просмотра информации о последних матчах Dota 2."""

    def __init__(self, bot: commands.Bot):
        """
        Инициализирует ког LastMatchCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
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
            # Используем safe_send для обработки ошибок отправки
            from utils.error_handler import safe_send_error
            await safe_send_error(ctx, "Ошибка: не удалось получить доступ к модулю привязок аккаунтов.")
            return

        # Определяем ID пользователя, для которого нужно получить ссылки
        target_user = member if member else ctx.author
        user_id = target_user.id

        # Получаем список привязанных Steam ID для этого пользователя
        # Убедимся, что links_manager существует
        if not hasattr(links_cog, 'links_manager'):
             from utils.error_handler import safe_send_error
             await safe_send_error(ctx, "Ошибка: внутренняя ошибка модуля привязок.")
             logger.error("Объект links_manager не найден в коге Links.")
             return

        try:
            # Получаем список ссылок (может быть пустым)
            user_links_list = await links_cog.links_manager.get_links(user_id)

        except Exception as e:
             from utils.error_handler import safe_send_error
             await safe_send_error(ctx, "Ошибка при получении привязанных аккаунтов.")
             logger.error(f"Ошибка при вызове links_manager.get_links: {e}", exc_info=True)
             return

        # Отмечаем взаимодействие как отложенное, т.к. запрос к API может занять время
        await ctx.defer()

        # Вызываем основную логику обработки команды из utils/dota_match_utils.py
        # Передаем список ID
        await handle_lastmatch(ctx, user_links_list, member)

async def setup(bot: commands.Bot):
    """
    Добавляет ког LastMatchCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(LastMatchCog(bot))
    logger.info("Ког LastMatchCog успешно загружен.")
