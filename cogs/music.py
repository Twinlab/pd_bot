# cogs/music.py
import discord
from discord.ext import commands
import logging
from typing import Optional

logger = logging.getLogger("bot")

# Импортируем функции из оптимизированного модуля
from utils.music_utils import (
    handle_play, handle_skip, handle_stop, handle_pause,
    handle_resume, handle_remove, handle_queue
)

class Music(commands.Cog):
    """Команды для воспроизведения музыки"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен")
    
    @commands.hybrid_command(description='Воспроизвести музыку')
    async def play(self, ctx, *, query: str):
        """Воспроизводит музыку из YouTube с возможностью поиска"""
        try:
            await handle_play(ctx, query)
        except Exception as e:
            logger.error(f"Ошибка в команде play: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")
    
    @commands.hybrid_command(description='Пропустить текущий трек')
    async def skip(self, ctx):
        """Пропускает текущий трек"""
        try:
            await handle_skip(ctx)
        except Exception as e:
            logger.error(f"Ошибка в команде skip: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")
    
    @commands.hybrid_command(description='Остановить воспроизведение')
    async def stop(self, ctx):
        """Останавливает воспроизведение и очищает очередь"""
        try:
            await handle_stop(ctx)
        except Exception as e:
            logger.error(f"Ошибка в команде stop: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")
    
    @commands.hybrid_command(description='Приостановить воспроизведение')
    async def pause(self, ctx):
        """Ставит воспроизведение на паузу"""
        try:
            await handle_pause(ctx)
        except Exception as e:
            logger.error(f"Ошибка в команде pause: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")
    
    @commands.hybrid_command(description='Возобновить воспроизведение')
    async def resume(self, ctx):
        """Возобновляет воспроизведение"""
        try:
            await handle_resume(ctx)
        except Exception as e:
            logger.error(f"Ошибка в команде resume: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")
    
    @commands.hybrid_command(description='Удалить трек из очереди')
    async def remove(self, ctx, position: int):
        """Удаляет трек из очереди по позиции"""
        try:
            await handle_remove(ctx, position)
        except Exception as e:
            logger.error(f"Ошибка в команде remove: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")
    
    @commands.hybrid_command(description='Показать очередь воспроизведения')
    async def queue(self, ctx):
        """Показывает очередь воспроизведения"""
        try:
            await handle_queue(ctx)
        except Exception as e:
            logger.error(f"Ошибка в команде queue: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {e}")

async def setup(bot):
    await bot.add_cog(Music(bot))