import discord
from discord.ext import commands
from typing import Optional, List, Union
import logging
import asyncio
import datetime

logger = logging.getLogger("bot")

class Admin(commands.Cog):
    """Административные команды для управления сервером"""
    
    def __init__(self, bot):
        self.bot = bot
        self.recent_purges = {}  # Для отслеживания недавних очисток
    
    async def safe_send(self, ctx, content, ephemeral=False, delete_after=None):
        """Безопасно отправляет сообщение в зависимости от типа команды"""
        try:
            is_slash = hasattr(ctx, 'interaction') and ctx.interaction is not None
            
            if is_slash:
                # Для slash-команд
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(content, ephemeral=ephemeral)
                else:
                    await ctx.interaction.followup.send(content, ephemeral=ephemeral)
            else:
                # Для обычных команд
                return await ctx.send(content, delete_after=delete_after)
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
    
    async def clear_messages(self, ctx, count: int = 10, user: discord.Member = None) -> int:
        """
        Очищает сообщения в канале с обходом ограничения в 14 дней.
        
        Args:
            ctx: Контекст команды
            count: Количество сообщений для удаления (по умолчанию 10)
            user: Если указан, удаляются только сообщения этого пользователя
            
        Returns:
            int: Количество удаленных сообщений
        """
        def check(msg):
            if user is None:
                return True
            else:
                return msg.author == user
        
        # Дата, до которой можно массово удалять сообщения (14 дней назад)
        two_weeks_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)
        
        # Получаем сообщения
        messages_to_delete = []
        async for msg in ctx.channel.history(limit=count):
            if check(msg):
                messages_to_delete.append(msg)
                if len(messages_to_delete) >= count:
                    break
        
        # Разделяем на группы: новые (< 14 дней) и старые (> 14 дней)
        recent_messages = [msg for msg in messages_to_delete if msg.created_at > two_weeks_ago]
        old_messages = [msg for msg in messages_to_delete if msg.created_at <= two_weeks_ago]
        
        # Счетчик удаленных сообщений
        deleted_count = 0
        
        # Удаляем новые сообщения пачкой (если они есть)
        if recent_messages:
            try:
                deleted = await ctx.channel.delete_messages(recent_messages)
                deleted_count += len(recent_messages)
            except discord.HTTPException as e:
                logger.error(f"Ошибка при массовом удалении сообщений: {e}")
                # Удаляем по одному, если массовое удаление не удалось
                for msg in recent_messages:
                    try:
                        await msg.delete()
                        deleted_count += 1
                    except:
                        pass
        
        # Удаляем старые сообщения по одному (если они есть)
        for msg in old_messages:
            try:
                await msg.delete()
                deleted_count += 1
                # Небольшая задержка, чтобы избежать рейт-лимитов
                await asyncio.sleep(0.5)
            except:
                pass
        
        return deleted_count
    
    @commands.hybrid_command(description='Очистить сообщения в канале')
    @commands.has_permissions(administrator=True)
    async def clear(self, ctx, count: Optional[int] = 10, user: Optional[discord.Member] = None):
        """
        Очищает указанное количество сообщений из канала.
        
        Параметры:
        count - количество сообщений для удаления (по умолчанию 10)
        user - пользователь, чьи сообщения нужно удалить (опционально)
        """
        try:
            # Проверка на разумные пределы
            if count > 100:
                await self.safe_send(ctx, "Для безопасности ограничено максимум 100 сообщений за раз.", ephemeral=True)
                count = 100
            
            # Защита от случайного повторного выполнения
            channel_id = ctx.channel.id
            current_time = datetime.datetime.now().timestamp()
            
            if channel_id in self.recent_purges:
                last_time, last_count = self.recent_purges[channel_id]
                # Если прошло меньше 10 секунд и количество больше 10
                if current_time - last_time < 10 and count > 10:
                    await self.safe_send(
                        ctx, 
                        f"Вы недавно удалили {last_count} сообщений. Подождите немного перед новым массовым удалением.",
                        ephemeral=True
                    )
                    return
            
            # Для slash-команд используем отложенный ответ
            is_slash = hasattr(ctx, 'interaction') and ctx.interaction is not None
            if is_slash:
                await ctx.defer(ephemeral=True)
            
            # Сохраняем информацию о текущей очистке
            self.recent_purges[channel_id] = (current_time, count)
            
            # Вызываем функцию очистки сообщений
            deleted_count = await self.clear_messages(ctx, count=count, user=user)
            
            # Формируем сообщение об успешном удалении
            message = f"Удалено {deleted_count} сообщений"
            if user:
                message += f" пользователя {user.display_name}"
            
            # Отправляем ответ
            await self.safe_send(ctx, message + ".", ephemeral=True if is_slash else False, delete_after=5 if not is_slash else None)
            
            # Логируем действие
            logger.info(f"Администратор {ctx.author} удалил {deleted_count} сообщений в канале {ctx.channel.name}")
                
        except discord.NotFound:
            # Игнорируем ошибку с потерянным взаимодействием
            logger.info("Взаимодействие не найдено, но команда была успешно выполнена")
        except Exception as e:
            logger.error(f"Ошибка при очистке сообщений: {e}", exc_info=True)
            await self.safe_send(ctx, f"Произошла ошибка: {e}", ephemeral=True if is_slash else False)
    
    @commands.hybrid_command(description='Кикнуть пользователя с сервера')
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = "Причина не указана"):
        """
        Кикает пользователя с сервера.
        
        Параметры:
        member - пользователь для кика
        reason - причина кика (опционально)
        """
        try:
            # Проверяем, что бот и автор команды имеют достаточно высокую роль
            if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
                await self.safe_send(ctx, "Вы не можете кикнуть участника с равной или более высокой ролью.", ephemeral=True)
                return
            
            if member.top_role >= ctx.guild.me.top_role:
                await self.safe_send(ctx, "У бота недостаточно прав для кика этого участника.", ephemeral=True)
                return
                
            # Отправляем пользователю DM, если возможно
            try:
                await member.send(f"Вы были кикнуты с сервера {ctx.guild.name}. Причина: {reason}")
            except:
                pass
                
            # Кикаем пользователя
            await member.kick(reason=f"От {ctx.author}: {reason}")
            
            # Отправляем подтверждение
            await self.safe_send(
                ctx, 
                f"Пользователь {member.mention} ({member.name}) был кикнут. Причина: {reason}"
            )
            
            # Логируем действие
            logger.info(f"Администратор {ctx.author} кикнул {member} по причине: {reason}")
            
        except discord.Forbidden:
            await self.safe_send(ctx, "У бота недостаточно прав для выполнения этого действия.", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка при кике пользователя: {e}", exc_info=True)
            await self.safe_send(ctx, f"Произошла ошибка: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))