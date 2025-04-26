import discord
import asyncio
from discord.ext import commands
import logging
from typing import Optional

# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

# Импортируем функции и класс плеера из оптимизированного модуля
from utils.music_utils import (
    handle_play, handle_skip, handle_stop, handle_pause,
    handle_resume, handle_remove, handle_queue,
    MusicPlayer # Импортируем класс плеера
)

class Music(commands.Cog):
    """Ког, предоставляющий команды для управления музыкальным плеером."""
    
    def __init__(self, bot):
        """Инициализирует ког Music."""
        self.bot = bot
        # Создаем единственный экземпляр плеера для этого кога
        self.player = MusicPlayer(bot)
        logger.info(f"Ког {self.__class__.__name__} загружен")

    # Добавляем метод cog_unload для попытки очистки плеера при выгрузке кога
    def cog_unload(self):
        """Пытается очистить ресурсы плеера при выгрузке кога."""
        logger.info(f"Ког {self.__class__.__name__} выгружается...")
        # Асинхронная очистка в синхронном cog_unload затруднительна.
        # Плеер должен сам обрабатывать остановку/очистку при отключении.
        # Можно попробовать остановить текущее воспроизведение, если оно есть.
        if self.player and self.player.current and self.bot.voice_clients:
            vc = discord.utils.get(self.bot.voice_clients, guild=self.player.text_channel.guild) # Найдем VC по каналу
            if vc and (vc.is_playing() or vc.is_paused()):
                logger.info("Остановка воспроизведения при выгрузке кога...")
                vc.stop() # Синхронная остановка

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Автоматически отключает бота, если он остается один в канале."""
        # Игнорируем событие, если оно вызвано самим ботом или не связано с каналом
        if member.id == self.bot.user.id or before.channel is None:
            return

        # Получаем голосовой клиент для сервера (гильдии), где произошло событие
        voice_client = member.guild.voice_client

        # Проверяем, подключен ли бот и произошло ли событие в его канале
        if not voice_client or before.channel != voice_client.channel:
            return

        # Небольшая задержка, чтобы дать Discord время обновить список участников
        await asyncio.sleep(1)

        # Проверяем, остался ли бот один в канале
        # Убедимся, что voice_client все еще существует после задержки
        voice_client = member.guild.voice_client
        if voice_client and len(voice_client.channel.members) == 1: # Только бот
            logger.info(f"Бот остался один в канале {voice_client.channel.name}. Запускаем автоотключение.")
            # Используем функцию из music_utils, передавая плеер и гильдию
            from utils.music_utils import auto_disconnect # Импортируем здесь, чтобы избежать циклического импорта
            # Вызываем функцию автоотключения, передавая текущий плеер
            await auto_disconnect(self.player, member.guild, voice_client.channel)

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
