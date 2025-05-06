"""Развлекательный ког с различными командами для участников сервера."""
import discord
from discord.ext import commands
from typing import Optional
import logging

from utils.error_handler import command_error_handler
from utils.avatar_utils import display_avatar
from utils.penis_utils import measure_penis
from utils.snipe_utils import show_sniped_message, save_deleted_message
from utils.deathbattle_utils import run_battle

logger = logging.getLogger("bot.fun") # Иерархическое имя логгера

class FunCog(commands.Cog):
    """Развлекательные команды для участников сервера."""

    def __init__(self, bot: commands.Bot):
        """
        Инициализирует ког FunCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен.") # Добавил точку в конце лог сообщения

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Обрабатывает удаленные сообщения для команды snipe"""
        # Блок try/except не нужен, т.к. ошибки listener не влияют на команды
        await save_deleted_message(message)

    @commands.hybrid_command(description='Запускает дезбаттл между двумя пользователями')
    @command_error_handler
    async def deathbattle(self, ctx: commands.Context, member1: Optional[discord.Member] = None, member2: Optional[discord.Member] = None):
        """
        Запускает битву между двумя пользователями с визуализацией сражения.

        Args:
            ctx: Контекст команды
            member1: Первый участник (опционально)
            member2: Второй участник (опционально)
        """
        await run_battle(ctx, member1, member2)

    @commands.hybrid_command(description='Показывает последнее удаленное сообщение')
    @command_error_handler
    async def snipe(self, ctx: commands.Context):
        """
        Показывает последнее удаленное сообщение в канале.

        Args:
            ctx: Контекст команды.
        """
        await show_sniped_message(ctx)

    @commands.hybrid_command(description='Показывает размер пениса')
    @command_error_handler
    async def penis(self, ctx: commands.Context, mentioned_user: Optional[discord.Member] = None):
        """
        Генерирует случайный размер пениса.

        Args:
            ctx: Контекст команды.
            mentioned_user: Пользователь, для которого измеряется (опционально, по умолчанию - автор команды).
        """
        await measure_penis(ctx, mentioned_user)

    @commands.hybrid_command(description='Показывает аватар пользователя')
    @command_error_handler
    async def avatar(self, ctx: commands.Context, mentioned_user: Optional[discord.Member] = None):
        """
        Показывает аватар указанного пользователя или автора команды.

        Args:
            ctx: Контекст команды.
            mentioned_user: Пользователь, чей аватар нужно показать (опционально, по умолчанию - автор команды).
        """
        await display_avatar(ctx, mentioned_user)

async def setup(bot: commands.Bot):
    """
    Добавляет ког FunCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(FunCog(bot))
    logger.info("Ког FunCog успешно загружен.")
