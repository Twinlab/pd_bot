"""Ког для просмотра информации о последних матчах Dota 2.

Этот модуль предоставляет команду для получения и отображения информации
о последних матчах Dota 2 для пользователей Discord. Функциональность включает:
- Получение данных о последнем матче через Steam API
- Отображение статистики матча в виде эмбеда Discord
- Поддержку просмотра статистики как для себя, так и для других пользователей

Для работы требуется предварительная привязка Steam ID через команду /link.
"""

import logging
from typing import Optional

import discord
from discord.ext import commands

from utils.cog_utils import log_cog_load
from utils.dota_match_utils import handle_lastmatch
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot.cogs.lastmatch")  # Иерархическое имя логгера


class LastMatchCog(commands.Cog):
    """Команды для просмотра информации о последних матчах Dota 2."""

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког LastMatchCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot: commands.Bot = bot
        # Используем нашу утилиту для логирования загрузки кога
        log_cog_load(self.__class__.__name__, "init")

    @commands.hybrid_command(description="Показать информацию о последнем матче Dota 2")
    @command_error_handler
    async def lastmatch(
        self, ctx: commands.Context, member: Optional[discord.Member] = None
    ) -> None:
        """Показывает информацию о последнем матче Dota 2.

        Для указанного пользователя (или автора команды).
        Требует предварительной привязки Steam ID через команду /link.
        """
        # Получаем доступ к когу LinksCog для получения привязок аккаунтов
        links_cog = self.bot.get_cog("LinksCog")
        if not links_cog:
            # Используем safe_send для обработки ошибок отправки
            from utils.error_handler import safe_send_error

            await safe_send_error(
                ctx, Exception("Ошибка: не удалось получить доступ к модулю привязок аккаунтов.")
            )
            return

        # Определяем ID пользователя, для которого нужно получить ссылки
        target_user = member if member else ctx.author
        user_id = target_user.id

        # Получаем список привязанных Steam ID для этого пользователя
        # Убедимся, что links_manager существует
        if not hasattr(links_cog, "links_manager"):
            from utils.error_handler import safe_send_error

            await safe_send_error(ctx, Exception("Ошибка: внутренняя ошибка модуля привязок."))
            logger.error("Объект links_manager не найден в коге Links.")
            return

        try:
            # Получаем список ссылок (может быть пустым)
            user_links_list = await links_cog.links_manager.get_links(user_id)

        except Exception as e:
            from utils.error_handler import safe_send_error

            await safe_send_error(ctx, Exception("Ошибка при получении привязанных аккаунтов."))
            logger.error(f"Ошибка при вызове links_manager.get_links: {e}", exc_info=True)
            return

        # Отмечаем взаимодействие как отложенное, т.к. запрос к API может занять время
        await ctx.defer()

        # Вызываем основную логику обработки команды из utils/dota_match_utils.py
        # Передаем список ID
        await handle_lastmatch(ctx, user_links_list, member)

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        logger.info(f"Ког {self.__class__.__name__} выгружен.")

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Обрабатывает ошибки, возникающие при выполнении команд в этом коге.

        Args:
            ctx: Контекст команды, где произошла ошибка.
            error: Объект ошибки.
        """
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас нет прав для выполнения этой команды.", ephemeral=True)
        elif isinstance(error, commands.CommandInvokeError):
            logger.error(
                f"Ошибка при выполнении команды: {error.original}", exc_info=error.original
            )
            await ctx.send(f"Произошла ошибка: {error.original}", ephemeral=True)
        else:
            logger.error(f"Необработанная ошибка в команде: {error}", exc_info=error)
            await ctx.send(f"Произошла неизвестная ошибка: {error}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког LastMatchCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(LastMatchCog(bot))
    # Используем нашу утилиту для логирования загрузки кога
    log_cog_load("LastMatchCog", "setup")
