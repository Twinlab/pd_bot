import discord
import asyncio
from discord.ext import commands
import logging
from typing import Optional

# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

# Импортируем функции и класс плеера из старой структуры
from utils.music_utils import (
    handle_play, handle_skip, handle_stop, handle_pause,
    handle_resume, handle_remove, handle_queue,
    MusicPlayer # Класс плеера все еще нужен для __init__ и on_voice_state_update
)

class Music(commands.Cog):
    """Ког, предоставляющий команды для управления музыкальным плеером."""

    def __init__(self, bot):
        """Инициализирует ког Music."""
        self.bot = bot
        # Создаем единственный экземпляр плеера для этого кога
        # В старой структуре плеер создавался здесь, а не по гильдиям
        self.player = MusicPlayer(bot)
        logger.info(f"Ког {self.__class__.__name__} загружен")

    # Метод cog_unload остается для очистки при выгрузке
    def cog_unload(self):
        """Пытается очистить ресурсы плеера при выгрузке кога."""
        logger.info(f"Ког {self.__class__.__name__} выгружается...")
        # Логика остановки воспроизведения при выгрузке
        if self.player and self.player.current and self.bot.voice_clients:
             # Пытаемся найти voice_client через text_channel (может быть None)
             guild_to_check = None
             if self.player.text_channel:
                 guild_to_check = self.player.text_channel.guild

             if guild_to_check:
                 vc = discord.utils.get(self.bot.voice_clients, guild=guild_to_check)
                 if vc and (vc.is_playing() or vc.is_paused()):
                     logger.info("Остановка воспроизведения при выгрузке кога...")
                     vc.stop() # Синхронная остановка

    # Обработчик on_voice_state_update возвращается к старой логике
    # (вызов auto_disconnect из music_utils)
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Автоматически отключает бота, если он остается один в канале."""
        if member.id == self.bot.user.id or before.channel is None:
            return

        voice_client = member.guild.voice_client
        if not voice_client or before.channel != voice_client.channel:
            return

        await asyncio.sleep(1) # Задержка

        # Перепроверяем voice_client
        voice_client = member.guild.voice_client
        if voice_client and len(voice_client.channel.members) == 1: # Только бот
            logger.info(f"Бот остался один в канале {voice_client.channel.name}. Запускаем автоотключение.")
            # Импортируем здесь, чтобы избежать циклического импорта, если music_utils импортирует что-то из когов
            try:
                from utils.music_utils import auto_disconnect
                # Передаем плеер, гильдию и канал
                await auto_disconnect(self.player, member.guild, voice_client.channel)
            except ImportError:
                 logger.error("Не удалось импортировать auto_disconnect из utils.music_utils")
            except Exception as e:
                 logger.error(f"Ошибка при вызове auto_disconnect: {e}", exc_info=True)


    # --- Команды (возвращаем вызовы handle_*) ---
    @commands.hybrid_command(name="play", description='Воспроизвести музыку или добавить в очередь')
    @command_error_handler
    async def play(self, ctx: commands.Context, *, query: str): # Возвращаем '*' для совместимости
        """
        Воспроизводит музыку по URL/поиску или добавляет в очередь.
        Автоматически подключается к вашему голосовому каналу.
        """
        await handle_play(ctx, query)

    @commands.hybrid_command(description='Пропустить текущий трек')
    @command_error_handler
    async def skip(self, ctx: commands.Context):
        """Голосует за пропуск трека или пропускает его (DJ/запросивший)."""
        await handle_skip(ctx)

    @commands.hybrid_command(description='Остановить воспроизведение и покинуть канал')
    @command_error_handler
    async def stop(self, ctx: commands.Context):
        """Останавливает музыку, очищает очередь и отключает бота."""
        await handle_stop(ctx)

    @commands.hybrid_command(description='Приостановить воспроизведение')
    @command_error_handler
    async def pause(self, ctx: commands.Context):
        """Ставит текущий трек на паузу."""
        await handle_pause(ctx)

    @commands.hybrid_command(description='Возобновить воспроизведение')
    @command_error_handler
    async def resume(self, ctx: commands.Context):
        """Возобновляет воспроизведение после паузы."""
        await handle_resume(ctx)

    @commands.hybrid_command(description='Удалить трек из очереди')
    @command_error_handler
    async def remove(self, ctx: commands.Context, position: int):
        """Удаляет трек из очереди по номеру (начиная с 1)."""
        await handle_remove(ctx, position)

    @commands.hybrid_command(description='Показать очередь воспроизведения')
    @command_error_handler
    async def queue(self, ctx: commands.Context):
        """Показывает текущий трек и следующие в очереди."""
        await handle_queue(ctx)

    # Команды volume, loop, shuffle удалены

async def setup(bot):
    await bot.add_cog(Music(bot))
