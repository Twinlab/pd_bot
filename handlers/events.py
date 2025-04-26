import discord
from discord.ext import commands
import logging
from typing import List, Optional, Union

# Импорты для музыки
try:
    from utils.music_utils import cleanup_player, auto_disconnect
except ImportError:
    cleanup_player = None
    auto_disconnect = None
    logger.warning("Модули для работы с музыкой не найдены")

logger = logging.getLogger("bot")

class Events(commands.Cog):
    """Ког для обработки основных событий Discord, таких как готовность бота,
       изменения в голосовых каналах, выход участников и ошибки команд."""
    
    def __init__(self, bot):
        """Инициализирует ког Events."""
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен")
        
    @commands.Cog.listener()
    async def on_ready(self):
        """Событие: вызывается, когда бот успешно подключился и готов к работе."""
        logger.info(f"Бот {self.bot.user.name} (ID: {self.bot.user.id}) готов к работе.")
        logger.info(f"Версия discord.py: {discord.__version__}")
        
        # Синхронизация slash-команд с Discord
        logger.info("Синхронизация slash-команд...")
        try:
            synced = await self.bot.tree.sync()
            command_names = [cmd.name for cmd in synced]
            logger.info(f"Синхронизировано {len(synced)} команд: {', '.join(command_names)}")
        except Exception as e:
            logger.error(f"Не удалось синхронизировать команды: {e}")
        
        # Установка статуса "Играет в..."
        await self.bot.change_presence(activity=discord.Game(name="Делаю милые вещи и пью чай"))
        logger.info("Статус бота установлен.")
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Событие: вызывается, когда участник покидает сервер."""
        try:
            # Найти канал general
            channel = discord.utils.get(member.guild.text_channels, name='general')
            if not channel:
                # Если #general не найден, ищем первый доступный текстовый канал
                logger.debug(f"Канал #general не найден на сервере {member.guild.name}, ищем другой канал...")
                channels = [c for c in member.guild.text_channels if c.permissions_for(member.guild.me).send_messages]
                if channels:
                    channel = channels[0]
            
            if channel:
                # Отправляем прощальное сообщение
                await channel.send(f"**{member.name}** ббак")
        except Exception as e:
            logger.error(f"Ошибка в on_member_remove: {e}")
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """
        Событие: вызывается при изменении голосового состояния участника
        (подключение/отключение/перемещение/mute/deafen и т.д.).
        Используется для автоматического отключения музыкального бота.
        """
        try:
            # Игнорируем, если пользователь не менял канал (например, вкл/выкл микрофон)
            if before.channel == after.channel:
                return
                
            # Проверяем, доступны ли функции из music_utils (могли не импортироваться)
            if cleanup_player is None or auto_disconnect is None:
                 logger.warning("Функции cleanup_player или auto_disconnect недоступны в on_voice_state_update.")
                 return
 
            # Получаем ког Music для доступа к плееру
            music_cog = self.bot.get_cog("Music")
            if not music_cog or not hasattr(music_cog, 'player'):
                logger.warning("Ког Music или его плеер не найдены в on_voice_state_update.")
                return

            player = music_cog.player

            # Если сам бот был отключен от канала
            if member.id == self.bot.user.id and before.channel and not after.channel:
                logger.info(f"Бот был отключен от канала {before.channel.name}")
                # Передаем плеер и имя гильдии
                await cleanup_player(player, member.guild.name)
                return

            # Если пользователь (не бот) покинул голосовой канал, в котором находится бот
            if before.channel and not member.bot:
                # Получаем голосовой клиент бота для этого сервера
                voice_client = member.guild.voice_client
                # Если бот подключен к тому же каналу, который покинул пользователь
                if voice_client and voice_client.channel == before.channel:
                    # Проверяем, остались ли в канале другие пользователи (кроме ботов)
                    users_in_channel = [m for m in before.channel.members if not m.bot]
                    
                    # Если в канале не осталось пользователей, запускаем автоотключение
                    if not users_in_channel:
                        logger.info(f"Последний пользователь покинул канал {before.channel.name}, запускаем автоотключение...")
                        # Передаем плеер, гильдию и голосовой канал
                        await auto_disconnect(player, member.guild, before.channel)
        except Exception as e:
            logger.error(f"Ошибка в on_voice_state_update: {e}", exc_info=True)
        
    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Глобальный обработчик ошибок для всех команд."""
        # Игнорируем ошибки "Команда не найдена"
        if isinstance(error, commands.CommandNotFound):
            return
            
        # Обработка стандартных ошибок discord.py
        if isinstance(error, commands.MissingRequiredArgument):
            await self._send_error(ctx, f"Отсутствует обязательный аргумент: `{error.param.name}`")
        elif isinstance(error, commands.BadArgument):
            await self._send_error(ctx, "Неверный аргумент команды")
        elif isinstance(error, commands.MissingPermissions):
            await self._send_error(ctx, "У вас недостаточно прав для выполнения этой команды")
        elif isinstance(error, commands.BotMissingPermissions):
            await self._send_error(ctx, f"У бота недостаточно прав: {', '.join(error.missing_permissions)}")
        elif isinstance(error, commands.CommandOnCooldown):
            await self._send_error(ctx, f"Команда на перезарядке. Попробуйте через {error.retry_after:.1f} сек.")
        elif isinstance(error, commands.NotOwner):
            await self._send_error(ctx, "Эта команда доступна только владельцу бота")
        else:
            # Логируем все остальные (необработанные) ошибки
            logger.error(f"Необработанная ошибка в команде '{ctx.command}': {error}", exc_info=True)
            # Можно добавить отправку сообщения пользователю о неизвестной ошибке, если нужно
            # await self._send_error(ctx, f"Произошла непредвиденная ошибка: {error}")
            
    async def _send_error(self, ctx: commands.Context, message: str):
        """Вспомогательный метод для отправки сообщения об ошибке пользователю."""
        try:
            is_slash = hasattr(ctx, 'interaction') and ctx.interaction is not None
            
            if is_slash:
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(message, ephemeral=True)
                else:
                    await ctx.interaction.followup.send(message, ephemeral=True)
            else:
                await ctx.send(message)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение об ошибке пользователю: {e}")
 
async def setup(bot):
    await bot.add_cog(Events(bot))
