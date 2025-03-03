# handlers/events.py
import discord
from discord.ext import commands
import logging
from typing import List, Optional, Union

logger = logging.getLogger("bot")

class Events(commands.Cog):
    """Обработчики основных событий Discord"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Ког {self.__class__.__name__} загружен")
        
    @commands.Cog.listener()
    async def on_ready(self):
        """Вызывается, когда бот готов к работе"""
        logger.info(f"Бот запущен как {self.bot.user.name}")
        logger.info(f"Discord.py версия: {discord.__version__}")
        
        # Синхронизация команд
        try:
            synced = await self.bot.tree.sync()
            command_names = [cmd.name for cmd in synced]
            logger.info(f"Синхронизировано {len(synced)} команд: {', '.join(command_names)}")
        except Exception as e:
            logger.error(f"Ошибка при синхронизации команд: {e}")
        
        # Установка статуса
        await self.bot.change_presence(activity=discord.Game(name="Делаю милые вещи и пью чай"))
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """
        Обработка удаленных сообщений.
        
        Сохраняет информацию об удаленных сообщениях для команды snipe.
        """
        # Пропускаем сообщения ботов и DM
        if message.author.bot or not message.guild:
            return
            
        try:
            from utils.snipe_utils import save_deleted_message
            await save_deleted_message(message)
        except ImportError:
            logger.warning("Модуль snipe_utils не найден")
        except Exception as e:
            logger.error(f"Ошибка при обработке удаленного сообщения: {e}")
    
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Отправляет сообщение при выходе пользователя с сервера"""
        try:
            # Найти канал general
            channel = discord.utils.get(member.guild.text_channels, name='general')
            if not channel:
                # Если general не найден, попробуем найти основной канал
                channels = [c for c in member.guild.text_channels if c.permissions_for(member.guild.me).send_messages]
                if channels:
                    channel = channels[0]  # Берем первый доступный канал
            
            if channel:
                await channel.send(f"**{member.name}** ббак")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о выходе участника: {e}")
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """
        Обрабатывает изменения в голосовых каналах.
        
        Отключает бота, когда все пользователи покидают канал.
        """
        try:
            # Если изменения не связаны с каналами, игнорируем
            if before.channel == after.channel:
                return
                
            # Импортируем утилиты для музыки
            from utils.music_utils import cleanup_player, auto_disconnect
            
            # Если это бот отключился от канала
            if member.id == self.bot.user.id and before.channel and not after.channel:
                await cleanup_player(member.guild)
                return
                
            # Если пользователь (не бот) покинул канал, где находится бот
            if before.channel and member != self.bot.user and not member.bot:
                # Проверяем, находится ли бот в этом канале
                voice_client = member.guild.voice_client
                if voice_client and voice_client.channel == before.channel:
                    # Проверяем, остались ли пользователи (не боты) в канале
                    users_in_channel = [m for m in before.channel.members if not m.bot]
                    
                    if not users_in_channel:
                        await auto_disconnect(member.guild, before.channel)
        except ImportError:
            logger.warning("Модули для работы с музыкой не найдены")
        except Exception as e:
            logger.error(f"Ошибка в обработчике voice_state_update: {e}")
    
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Глобальный обработчик ошибок команд"""
        # Игнорируем некоторые типы ошибок
        if isinstance(error, commands.CommandNotFound):
            return
            
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
            # Логируем необработанные ошибки
            logger.error(f"Необработанная ошибка команды: {error}", exc_info=True)
            
    async def _send_error(self, ctx, message: str):
        """Отправляет сообщение об ошибке с правильной обработкой slash-команд"""
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
            logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")

async def setup(bot):
    await bot.add_cog(Events(bot))