import discord
from discord.ext import commands # Явно перезаписываем импорт
import logging
from typing import List, Optional, Union
import asyncio

# Импорты для музыки (возвращаем)
try:
    from utils.music_utils import cleanup_player, auto_disconnect
    # Пытаемся импортировать плеер для проверки типа, но не обязательно
    from utils.music_utils import MusicPlayer
except ImportError:
    cleanup_player = None
    auto_disconnect = None
    MusicPlayer = None # Определяем как None, если импорт не удался
    logger.warning("Модули для работы с музыкой не найдены")

logger = logging.getLogger("bot")

class Events(commands.Cog):
    """Ког для обработки основных событий Discord."""

    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен")

    @commands.Cog.listener()
    async def on_ready(self):
        """Событие: бот готов к работе."""
        logger.info(f"Бот {self.bot.user.name} (ID: {self.bot.user.id}) готов к работе.")
        logger.info(f"Версия discord.py: {discord.__version__}")

        # Синхронизация slash-команд
        logger.info("Синхронизация slash-команд...")
        try:
            synced = await self.bot.tree.sync()
            command_names = [cmd.name for cmd in synced]
            logger.info(f"Синхронизировано {len(synced)} команд: {', '.join(command_names)}")
        except Exception as e:
            logger.error(f"Не удалось синхронизировать команды: {e}")

        # Установка статуса
        await self.bot.change_presence(activity=discord.Game(name="Делаю милые вещи и пью чай"))
        logger.info("Статус бота установлен.")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Событие: участник покинул сервер."""
        try:
            channel = discord.utils.get(member.guild.text_channels, name='general')
            if not channel:
                logger.debug(f"Канал #general не найден на сервере {member.guild.name}, ищем другой канал...")
                channels = [c for c in member.guild.text_channels if c.permissions_for(member.guild.me).send_messages]
                if channels: channel = channels[0]

            if channel: await channel.send(f"**{member.name}** ббак")
        except Exception as e: logger.error(f"Ошибка в on_member_remove: {e}")

    # Возвращаем старую логику on_voice_state_update
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """
        Событие: вызывается при изменении голосового состояния участника.
        Используется для автоматического отключения музыкального бота.
        """
        try:
            if before.channel == after.channel: return # Игнорируем смену состояния без смены канала

            # Получаем плеер из кога Music (предполагаем, что он там один)
            music_cog = self.bot.get_cog("Music")
            player = getattr(music_cog, 'player', None) if music_cog else None

            # Проверяем, доступны ли функции и плеер
            if cleanup_player is None or auto_disconnect is None or MusicPlayer is None:
                 # logger.warning("Функции cleanup_player/auto_disconnect или класс MusicPlayer недоступны.") # Убрано, т.к. может спамить
                 return
            if not isinstance(player, MusicPlayer): # Проверяем, что плеер действительно есть
                 # logger.warning("Экземпляр плеера не найден в коге Music.") # Убрано
                 return

            # Если сам бот был отключен от канала
            if member.id == self.bot.user.id and before.channel and not after.channel:
                logger.info(f"Бот был отключен от канала {before.channel.name}")
                # Передаем плеер и имя гильдии
                await cleanup_player(player, member.guild.name)
                return

            # Если пользователь (не бот) покинул голосовой канал, в котором находится бот
            if before.channel and not member.bot:
                voice_client = member.guild.voice_client
                if voice_client and voice_client.channel == before.channel:
                    await asyncio.sleep(1) # Даем время на обновление списка участников
                    # Перепроверяем voice_client и количество участников
                    voice_client = member.guild.voice_client
                    if voice_client and len(voice_client.channel.members) == 1: # Если остался только бот
                        logger.info(f"Последний пользователь покинул канал {before.channel.name}, запускаем автоотключение...")
                        # Передаем плеер, гильдию и голосовой канал
                        await auto_disconnect(player, member.guild, before.channel)
        except Exception as e:
            logger.error(f"Ошибка в on_voice_state_update: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Глобальный обработчик ошибок для префиксных команд."""
        if isinstance(error, commands.CommandNotFound): return

        if isinstance(error, commands.MissingRequiredArgument): message = f"Отсутствует аргумент: `{error.param.name}`"
        elif isinstance(error, commands.BadArgument): message = "Неверный аргумент команды"
        elif isinstance(error, commands.MissingPermissions): message = "Нет прав для выполнения команды"
        elif isinstance(error, commands.BotMissingPermissions): message = f"У бота нет прав: {', '.join(error.missing_permissions)}"
        elif isinstance(error, commands.CommandOnCooldown): message = f"Перезарядка. Попробуйте через {error.retry_after:.1f} сек."
        elif isinstance(error, commands.NotOwner): message = "Команда только для владельца бота"
        else:
            logger.error(f"Необработанная ошибка в префиксной команде '{ctx.command}': {error}", exc_info=True)
            message = f"Произошла ошибка: {error}"
        await self._send_error(ctx, message)

    async def _send_error(self, ctx: commands.Context, message: str):
        """Вспомогательный метод для отправки сообщения об ошибке (для префиксных команд)."""
        try:
            await ctx.send(f"❌ {message}")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение об ошибке пользователю: {e}")

async def setup(bot):
    await bot.add_cog(Events(bot))
