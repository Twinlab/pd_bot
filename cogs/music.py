import discord
from discord.ext import commands
import logging
from typing import Optional

# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

# Импортируем функции из оптимизированного модуля
from utils.music_utils import (
    handle_play, handle_skip, handle_stop, handle_pause,
    handle_resume, handle_remove, handle_queue
)

class Music(commands.Cog):
    """Ког, предоставляющий команды для управления музыкальным плеером."""
    
    def __init__(self, bot):
        """Инициализирует ког Music."""
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен")
    
    @commands.hybrid_command(description='Воспроизвести музыку')
    @command_error_handler
    async def play(self, ctx: commands.Context, *, query: str):
        """
        Воспроизводит музыку по URL или ищет на YouTube по запросу.
        Добавляет найденный трек в очередь.
        """
        await handle_play(ctx, query)

    @commands.hybrid_command(description='Пропустить текущий трек')
    @command_error_handler
    async def skip(self, ctx: commands.Context):
        """
        Голосует за пропуск текущего трека или пропускает его,
        если у пользователя есть права (DJ или запросивший трек).
        """
        await handle_skip(ctx)

    @commands.hybrid_command(description='Остановить воспроизведение')
    @command_error_handler
    async def stop(self, ctx: commands.Context):
        """Останавливает воспроизведение, очищает очередь и отключает бота от голосового канала."""
        await handle_stop(ctx)

    @commands.hybrid_command(description='Приостановить воспроизведение')
    @command_error_handler
    async def pause(self, ctx: commands.Context):
        """Приостанавливает воспроизведение текущего трека."""
        await handle_pause(ctx)

    @commands.hybrid_command(description='Возобновить воспроизведение')
    @command_error_handler
    async def resume(self, ctx: commands.Context):
        """Возобновляет воспроизведение после паузы."""
        await handle_resume(ctx)

    @commands.hybrid_command(description='Удалить трек из очереди')
    @command_error_handler
    async def remove(self, ctx: commands.Context, position: int):
        """
        Удаляет трек из очереди по указанному номеру позиции.
        Требует прав DJ или быть запросившим трек.
        """
        await handle_remove(ctx, position)

    @commands.hybrid_command(description='Показать очередь воспроизведения')
    @command_error_handler
    async def queue(self, ctx: commands.Context):
        """Отображает текущий трек и следующие несколько треков в очереди."""
        await handle_queue(ctx)

async def setup(bot):
    await bot.add_cog(Music(bot))
