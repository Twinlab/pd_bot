"""Ког для просмотра информации о последних матчах Dota 2.

Этот модуль предоставляет команду для получения и отображения информации
о последних матчах Dota 2 для пользователей Discord. Функциональность включает:
- Получение данных о последнем матче через Steam API
- Отображение статистики матча в виде эмбеда Discord
- Поддержку просмотра статистики как для себя, так и для других пользователей

Для работы требуется привязка аккаунта во вкладке «Аккаунты» команды /profile.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.dota_match_utils import handle_lastmatch
from utils.error_handler import command_error_handler, safe_send_error
from utils.links_data_manager import LinksDataManager

logger = logging.getLogger("bot.cogs.lastmatch")


class LastMatchCog(commands.Cog):
    """Команды для просмотра информации о последних матчах Dota 2."""

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког LastMatchCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot: commands.Bot = bot
        self.links_manager = LinksDataManager()

    async def send_last_match(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
    ) -> None:
        """Загружает привязки и отправляет карточку последнего матча."""
        target_user = member if member else ctx.author
        try:
            user_links_list = await self.links_manager.get_links(target_user.id)
        except Exception as e:
            await safe_send_error(ctx, "Ошибка при получении привязанных аккаунтов.")
            logger.error(f"Ошибка при вызове links_manager.get_links: {e}", exc_info=True)
            return

        await handle_lastmatch(ctx, user_links_list, member)

    @commands.hybrid_command(description="Показать информацию о последнем матче Dota 2")
    @app_commands.describe(member="Чей матч показать (по умолчанию — твой)")
    @command_error_handler
    async def lastmatch(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        """Показывает информацию о последнем матче Dota 2.

        Для указанного пользователя (или автора команды).
        Требует привязки аккаунта во вкладке «Аккаунты» команды /profile.
        """
        await ctx.defer()
        await self.send_last_match(ctx, member)

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        logger.info(f"Ког {self.__class__.__name__} выгружен.")


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког LastMatchCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(LastMatchCog(bot))
    logger.info("Ког LastMatchCog успешно загружен.")
