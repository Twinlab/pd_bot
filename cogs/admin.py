import discord
from discord.ext import commands
from typing import Optional, List, Union, Dict, Tuple
import logging
import asyncio
import datetime

# Импортируем обработчик ошибок и безопасную отправку
from utils.error_handler import command_error_handler, safe_send

logger = logging.getLogger("bot")

class Admin(commands.Cog):
    """Административные команды для управления сервером"""
    
    def __init__(self, bot):
        self.bot = bot
        # Словарь для отслеживания времени последней очистки в каждом канале {channel_id: (timestamp, count)}
        self.recent_purges: Dict[int, Tuple[float, int]] = {}

 
    async def clear_messages(self, ctx: commands.Context, count: int = 10, user: Optional[discord.Member] = None) -> int:
        """
        Очищает сообщения в канале с обходом ограничения в 14 дней.
        
        Args:
            ctx: Контекст команды.
            count: Количество сообщений для удаления (по умолчанию 10).
            user: Если указан, удаляются только сообщения этого пользователя.
            
        Returns:
            int: Фактическое количество удаленных сообщений.
        """
        # Вспомогательная функция для проверки, нужно ли удалять сообщение
        def check(msg: discord.Message) -> bool:
            if user is None:
                return True
            else:
                return msg.author == user
        
        # Discord API позволяет массово удалять только сообщения не старше 14 дней
        two_weeks_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)
        
        # Собираем сообщения для удаления, учитывая лимит count
        messages_to_delete = []
        async for msg in ctx.channel.history(limit=count):
            if check(msg):
                messages_to_delete.append(msg)
                if len(messages_to_delete) >= count:
                    break
        
        # Разделяем собранные сообщения на "новые" (можно удалить пачкой) и "старые" (нужно удалять по одному)
        recent_messages = [msg for msg in messages_to_delete if msg.created_at > two_weeks_ago]
        old_messages = [msg for msg in messages_to_delete if msg.created_at <= two_weeks_ago]
        
        deleted_count = 0
        
        # Пытаемся удалить "новые" сообщения пачкой через delete_messages
        if recent_messages:
            try:
                deleted = await ctx.channel.delete_messages(recent_messages)
                deleted_count += len(deleted) # Используем длину возвращенного списка удаленных сообщений
            except discord.HTTPException as e:
                logger.warning(f"Не удалось массово удалить сообщения, пробуем по одному: {e}")
                # Если пачковое удаление не удалось (например, из-за ошибки API), удаляем по одному
                for msg in recent_messages:
                    try:
                        await msg.delete()
                        deleted_count += 1
                    except discord.NotFound:
                         pass # Сообщение уже могло быть удалено
                    except Exception as e_single:
                         logger.warning(f"Не удалось удалить новое сообщение {msg.id} по одному: {e_single}")
        
        # Удаляем "старые" сообщения по одному
        for msg in old_messages:
            try:
                await msg.delete()
                deleted_count += 1
                # Небольшая задержка между удалениями, чтобы избежать rate limit Discord API
                await asyncio.sleep(0.5)
            except discord.NotFound:
                 pass # Сообщение уже могло быть удалено
            except Exception as e:
                 logger.warning(f"Не удалось удалить старое сообщение {msg.id}: {e}")
        
        return deleted_count
    
    @commands.hybrid_command(description='Очистить сообщения в канале')
    @commands.has_permissions(administrator=True)
    @command_error_handler
    async def clear(self, ctx, count: Optional[int] = 10, user: Optional[discord.Member] = None):
        """
        Очищает указанное количество сообщений из канала.
        
        Параметры:
        count - количество сообщений для удаления (по умолчанию 10, макс 100).
        user - пользователь, чьи сообщения нужно удалить (опционально).
        """
        # Проверка на максимальное количество удаляемых сообщений за раз
        if count > 100:
            await safe_send(ctx, "Для безопасности ограничено максимум 100 сообщений за раз.", ephemeral=True)
            count = 100
            
        # Защита от спама командой /clear в одном канале
        channel_id = ctx.channel.id
        current_time = datetime.datetime.now().timestamp()
            
        if channel_id in self.recent_purges:
            last_time, last_count = self.recent_purges[channel_id]
            # Блокируем повторный вызов с count > 10, если с прошлого вызова прошло < 10 секунд
            if current_time - last_time < 10 and count > 10:
                await safe_send(
                    ctx,
                    f"Вы недавно удалили {last_count} сообщений. Подождите немного перед новым массовым удалением.",
                    ephemeral=True
                )
                return
            
        # Для slash-команд используем отложенный ответ, т.к. удаление может занять время
        is_slash = hasattr(ctx, 'interaction') and ctx.interaction is not None
        if is_slash:
            await ctx.defer(ephemeral=True) # Ответ будет виден только автору команды
            
        # Запоминаем время и количество для защиты от спама
        self.recent_purges[channel_id] = (current_time, count)
            
        # Выполняем фактическое удаление сообщений
        deleted_count = await self.clear_messages(ctx, count=count, user=user)
            
        # Формируем сообщение об успешном удалении
        message = f"Удалено {deleted_count} сообщений"
        if user:
            message += f" пользователя {user.display_name}"
            
        # Отправляем подтверждение (эфемерное для slash, удаляемое через 5 сек для префиксных)
        await safe_send(ctx, message + ".", ephemeral=True if is_slash else False, delete_after=5 if not is_slash else None)
            
        # Логируем действие администратора
        logger.info(f"Администратор {ctx.author} удалил {deleted_count} сообщений в канале {ctx.channel.name}")

    @commands.hybrid_command(description='Кикнуть пользователя с сервера')
    @commands.has_permissions(kick_members=True)
    @command_error_handler
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = "Причина не указана"):
        """
        Кикает пользователя с сервера.
        
        Параметры:
        member - пользователь для кика.
        reason - причина кика (опционально).
        """
        # Проверка иерархии ролей: нельзя кикнуть пользователя с ролью выше или равной вашей (кроме владельца сервера)
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            await safe_send(ctx, "Вы не можете кикнуть участника с равной или более высокой ролью.", ephemeral=True)
            return
            
        # Проверка иерархии ролей: бот не может кикнуть пользователя с ролью выше или равной своей
        if member.top_role >= ctx.guild.me.top_role:
            await safe_send(ctx, "У бота недостаточно прав для кика этого участника.", ephemeral=True)
            return
                
        # Пытаемся отправить личное сообщение пользователю о кике
        try:
            await member.send(f"Вы были кикнуты с сервера {ctx.guild.name}. Причина: {reason}")
        except discord.Forbidden:
             logger.warning(f"Не удалось отправить DM пользователю {member} при кике (ЛС закрыты?).")
        except Exception as dm_error:
             logger.error(f"Ошибка при отправке DM пользователю {member} при кике: {dm_error}")
                
        # Выполняем кик
        await member.kick(reason=f"Кикнут {ctx.author.name}: {reason}")
            
        # Отправляем подтверждение в канал
        await safe_send(
            ctx,
            f"Пользователь {member.mention} ({member.name}) был кикнут. Причина: {reason}"
        )
            
        # Логируем действие администратора
        logger.info(f"Администратор {ctx.author} кикнул {member} по причине: {reason}")

async def setup(bot):
    await bot.add_cog(Admin(bot))
