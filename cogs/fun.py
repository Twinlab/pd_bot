# cogs/fun.py
import discord
from discord.ext import commands
from typing import Optional
import logging

logger = logging.getLogger("bot")

# Импортируем функциональность из утилит
from utils.avatar_utils import display_avatar
from utils.penis_utils import measure_penis
from utils.snipe_utils import show_sniped_message
from utils.deathbattle_utils import run_battle

class Fun(commands.Cog):
    """Развлекательные команды для участников сервера"""

    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Обрабатывает удаленные сообщения для команды snipe"""
        try:
            from utils.snipe_utils import save_deleted_message
            await save_deleted_message(message)
        except Exception as e:
            logger.error(f"Ошибка при обработке удаленного сообщения: {e}", exc_info=True)

    @commands.hybrid_command(description='Запускает дезбаттл между двумя пользователями')
    async def deathbattle(self, ctx, member1: Optional[discord.Member] = None, member2: Optional[discord.Member] = None):
        """
        Запускает битву между двумя пользователями с визуализацией сражения.

        Args:
            ctx: Контекст команды
            member1: Первый участник (опционально)
            member2: Второй участник (опционально)
        """
        try:
            await run_battle(ctx, member1, member2)
        except Exception as e:
            logger.error(f"Ошибка в команде deathbattle: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")

    @commands.hybrid_command(description='Показывает последнее удаленное сообщение')
    async def snipe(self, ctx):
        """
        Показывает последнее удаленное сообщение в канале.

        Args:
            ctx: Контекст команды
        """
        try:
            await show_sniped_message(ctx)
        except Exception as e:
            logger.error(f"Ошибка в команде snipe: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")

    @commands.hybrid_command(description='Показывает размер пениса')
    async def penis(self, ctx, mentioned_user: Optional[discord.Member] = None):
        """
        Генерирует случайный размер пениса.

        Args:
            ctx: Контекст команды
            mentioned_user: Пользователь, чей аватар нужно показать (опционально)
        """
        try:
            await measure_penis(ctx, mentioned_user)
        except Exception as e:
            logger.error(f"Ошибка в команде penis: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")

    @commands.hybrid_command(description='Показывает аватар пользователя')
    async def avatar(self, ctx, mentioned_user: Optional[discord.Member] = None):
        """
        Показывает аватар указанного пользователя или автора команды.

        Args:
            ctx: Контекст команды
            mentioned_user: Пользователь, чей аватар нужно показать (опционально)
        """
        try:
            await display_avatar(ctx, mentioned_user)
        except Exception as e:
            logger.error(f"Ошибка в команде avatar: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")

async def setup(bot):
    await bot.add_cog(Fun(bot))
