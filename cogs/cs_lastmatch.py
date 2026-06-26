"""Ког для просмотра информации о последних матчах CS2 (FACEIT).

Команда ``/cslastmatch`` получает данные о последнем матче CS2 пользователя через
FACEIT Data API и показывает их в виде Components V2 контейнера. Требует
предварительной привязки аккаунта FACEIT через ``/cslink``.
"""

import logging

import discord
from discord.ext import commands

from utils.cs_links_data_manager import CsLinksDataManager
from utils.cs_match_utils import handle_cs_lastmatch
from utils.error_handler import command_error_handler, safe_send_error

logger = logging.getLogger("bot.cogs.cs_lastmatch")


class CsLastMatchCog(commands.Cog):
    """Команды для просмотра информации о последних матчах CS2."""

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког CsLastMatchCog."""
        self.bot: commands.Bot = bot
        self.links_manager = CsLinksDataManager()

    @commands.hybrid_command(description="Показать информацию о последнем матче CS2 (FACEIT)")
    @command_error_handler
    async def cslastmatch(
        self, ctx: commands.Context, member: discord.Member | None = None
    ) -> None:
        """Показывает информацию о последнем матче CS2.

        Для указанного пользователя (или автора команды). Требует привязки
        аккаунта FACEIT через команду `/cslink`.
        """
        target_user = member if member else ctx.author
        user_id = target_user.id

        try:
            links = await self.links_manager.get_links(user_id)
        except Exception as e:
            await safe_send_error(ctx, "Ошибка при получении привязанных аккаунтов.")
            logger.error(f"Ошибка при вызове cs links_manager.get_links: {e}", exc_info=True)
            return

        await ctx.defer()
        await handle_cs_lastmatch(ctx, links, member)

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        logger.info(f"Ког {self.__class__.__name__} выгружен.")


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког CsLastMatchCog к боту."""
    await bot.add_cog(CsLastMatchCog(bot))
    logger.info("Ког CsLastMatchCog успешно загружен.")
