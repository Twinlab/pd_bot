import discord
from discord.ext import commands
from typing import Optional
import logging

# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

# Импортируем функциональность из утилит
from utils.avatar_utils import display_avatar
from utils.penis_utils import measure_penis
from utils.snipe_utils import show_sniped_message, save_deleted_message
from utils.deathbattle_utils import run_battle

class Fun(commands.Cog):
    """Развлекательные команды для участников сервера"""

    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен (минимальная версия)") # Added note

    # @commands.Cog.listener() # Commented out
    # async def on_message_delete(self, message: discord.Message): # Commented out
    #     """ # Commented out
    #     Слушатель событий: вызывается при удалении сообщения. # Commented out
    #     Сохраняет информацию об удаленном сообщении для команды /snipe. # Commented out
    #     """ # Commented out
    #     # try: # Commented out
    #     #     await save_deleted_message(message) # Commented out
    #     # except Exception as e: # Commented out
    #     #     logger.error(f"Ошибка при обработке удаленного сообщения: {e}", exc_info=True) # Commented out
    #     pass # Added pass

    # @commands.hybrid_command(description='Запускает дезбаттл между двумя пользователями') # Commented out
    # @command_error_handler # Commented out
    # async def deathbattle(self, ctx, member1: Optional[discord.Member] = None, member2: Optional[discord.Member] = None): # Commented out
    #     """ # Commented out
    #     Запускает битву между двумя пользователями с визуализацией сражения. # Commented out
    #     # Commented out
    #     Args: # Commented out
    #         ctx: Контекст команды # Commented out
    #         member1: Первый участник (опционально) # Commented out
    #         member2: Второй участник (опционально) # Commented out
    #     """ # Commented out
    #     # await run_battle(ctx, member1, member2) # Commented out
    #     pass # Added pass

    # @commands.hybrid_command(description='Показывает последнее удаленное сообщение') # Commented out
    # @command_error_handler # Commented out
    # async def snipe(self, ctx): # Commented out
    #     """ # Commented out
    #     Показывает последнее удаленное сообщение в канале. # Commented out
    #     # Commented out
    #     Args: # Commented out
    #         ctx: Контекст команды # Commented out
    #     """ # Commented out
    #     # await show_sniped_message(ctx) # Commented out
    #     pass # Added pass

    # @commands.hybrid_command(description='Показывает размер пениса') # Commented out
    # @command_error_handler # Commented out
    # async def penis(self, ctx, mentioned_user: Optional[discord.Member] = None): # Commented out
    #     """ # Commented out
    #     Генерирует случайный размер пениса. # Commented out
    #     # Commented out
    #     Args: # Commented out
    #         ctx: Контекст команды # Commented out
    #         mentioned_user: Пользователь, чей аватар нужно показать (опционально) # Commented out
    #     """ # Commented out
    #     # await measure_penis(ctx, mentioned_user) # Commented out
    #     pass # Added pass

    # @commands.hybrid_command(description='Показывает аватар пользователя') # Commented out
    # @command_error_handler # Commented out
    # async def avatar(self, ctx, mentioned_user: Optional[discord.Member] = None): # Commented out
    #     """ # Commented out
    #     Показывает аватар указанного пользователя или автора команды. # Commented out
    #     # Commented out
    #     Args: # Commented out
    #         ctx: Контекст команды # Commented out
    #         mentioned_user: Пользователь, чей аватар нужно показать (опционально) # Commented out
    #     """ # Commented out
    #     # await display_avatar(ctx, mentioned_user) # Commented out
    #     pass # Added pass

async def setup(bot):
    await bot.add_cog(Fun(bot))
