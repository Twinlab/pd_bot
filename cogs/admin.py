"""Административный ког с командами для управления ботом и сервером."""
import discord
from discord.ext import commands
from typing import Optional, Dict, Tuple # Убираем List и Union, они не используются в аннотациях
import logging
import asyncio
import datetime
import subprocess
import os

from utils.error_handler import command_error_handler, safe_send

logger = logging.getLogger("bot.admin") # Используем иерархическое имя логгера

class AdminCog(commands.Cog):
    """Ког с административными командами для управления ботом и сервером."""

    def __init__(self, bot: commands.Bot):
        """
        Инициализирует административный ког.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot = bot
        # Словарь для отслеживания времени последней очистки {channel_id: (timestamp, count)}
        # Используется для предотвращения спама командой clear
        self.recent_purges: Dict[int, Tuple[float, int]] = {}

    async def _clear_messages_helper(self, ctx: commands.Context, count: int, user: Optional[discord.Member] = None) -> int:
        """
        Вспомогательная функция для удаления сообщений, обходящая ограничение в 14 дней.
        Удаляет "новые" сообщения пачкой, "старые" - по одному.

        Args:
            ctx: Контекст команды.
            count: Желаемое количество сообщений для удаления.
            user: Если указан, удаляются только сообщения этого пользователя.

        Returns:
            int: Фактическое количество удаленных сообщений.
        """
        def check(msg: discord.Message) -> bool:
            return user is None or msg.author == user

        # Discord API позволяет массово удалять только сообщения не старше 14 дней
        two_weeks_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)

        messages_to_delete = []
        # Собираем историю сообщений (берем с запасом, т.к. будем фильтровать)
        async for msg in ctx.channel.history(limit=count * 2):
            if check(msg):
                messages_to_delete.append(msg)
                if len(messages_to_delete) >= count:
                    break # Набрали нужное количество

        # Разделяем сообщения на "новые" (можно удалить пачкой) и "старые" (удаляем по одному)
        recent_messages = [msg for msg in messages_to_delete if msg.created_at > two_weeks_ago]
        old_messages = [msg for msg in messages_to_delete if msg.created_at <= two_weeks_ago]

        deleted_count = 0

        # Массовое удаление недавних сообщений
        if recent_messages:
            try:
                deleted = await ctx.channel.delete_messages(recent_messages)
                deleted_count += len(deleted)
            except discord.HTTPException as e:
                logger.warning(f"Не удалось массово удалить сообщения, пробуем по одному: {e}")
                # Если пачковое удаление не удалось, пробуем удалить по одному
                for msg in recent_messages:
                    try:
                        await msg.delete()
                        deleted_count += 1
                    except discord.NotFound:
                         pass
                    except Exception as e_single:
                         logger.warning(f"Не удалось удалить новое сообщение {msg.id} по одному: {e_single}")

        # Удаление старых сообщений по одному
        for msg in old_messages:
            try:
                await msg.delete()
                deleted_count += 1
                await asyncio.sleep(0.5) # Небольшая задержка между удалениями старых сообщений
            except discord.NotFound:
                 pass # Сообщение уже удалено
            except Exception as e:
                 logger.warning(f"Не удалось удалить старое сообщение {msg.id}: {e}")

        return deleted_count

    @commands.hybrid_command(description='Очистить сообщения в канале')
    @commands.has_permissions(manage_messages=True) # Права на управление сообщениями
    @command_error_handler
    async def clear(self, ctx, count: Optional[int] = 10, user: Optional[discord.Member] = None):
        """
        Очищает указанное количество сообщений из текущего канала.

        Можно указать пользователя, чьи сообщения нужно удалить.
        Обходит ограничение Discord API на удаление сообщений старше 14 дней.
        Есть защита от слишком частого использования команды.

        Параметры:
        count: Количество сообщений для удаления (1-100, по умолчанию 10).
        user: Пользователь, чьи сообщения нужно удалить (опционально).
        """
        if not (1 <= count <= 100):
            await safe_send(ctx, "Количество сообщений должно быть от 1 до 100.", ephemeral=True)
            return

        # Защита от спама командой clear
        channel_id = ctx.channel.id
        current_time = datetime.datetime.now().timestamp()

        if channel_id in self.recent_purges:
            last_time, last_count = self.recent_purges[channel_id]
            # Блокируем повторный вызов с count > 10, если прошло < 10 секунд
            if current_time - last_time < 10 and count > 10:
                await safe_send(
                    ctx,
                    f"Вы недавно удалили {last_count} сообщений. Подождите немного перед новым массовым удалением.",
                    ephemeral=True
                )
                return

        is_slash = hasattr(ctx, 'interaction') and ctx.interaction is not None
        if is_slash:
            await ctx.defer(ephemeral=True) # Отложенный ответ, видимый только автору

        # Запоминаем время и количество для защиты от спама
        self.recent_purges[channel_id] = (current_time, count)

        # Выполняем фактическое удаление
        deleted_count = await self._clear_messages_helper(ctx, count=count, user=user)

        # Формируем и отправляем сообщение о результате
        message = f"Удалено {deleted_count} сообщений"
        if user:
            message += f" пользователя {user.display_name}"

        # Отправляем подтверждение (эфемерное для slash, удаляемое через 5 сек для префиксных)
        await safe_send(ctx, message + ".", ephemeral=True if is_slash else False, delete_after=5 if not is_slash else None)

        logger.info(f"Администратор {ctx.author} удалил {deleted_count} сообщений в канале {ctx.channel.name}")

    @commands.hybrid_command(description='Кикнуть пользователя с сервера')
    @commands.has_permissions(kick_members=True)
    @command_error_handler
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = "Причина не указана"):
        """
        Кикает пользователя с сервера.

        Параметры:
        member: Пользователь для кика (@упоминание или ID).
        reason: Причина кика (опционально).
        """
        # Проверка иерархии ролей: нельзя кикнуть пользователя с ролью выше или равной вашей
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            await safe_send(ctx, "Вы не можете кикнуть участника с равной или более высокой ролью.", ephemeral=True)
            return
        # Проверка иерархии ролей: бот не может кикнуть пользователя с ролью выше или равной своей
        if member.top_role >= ctx.guild.me.top_role:
            await safe_send(ctx, "У бота недостаточно прав для кика этого участника.", ephemeral=True)
            return

        # Пытаемся отправить личное сообщение пользователю о кике
        try:
            await member.send(f"Вы были кикнуты с сервера **{ctx.guild.name}**. Причина: {reason}")
        except discord.Forbidden:
             logger.warning(f"Не удалось отправить DM пользователю {member} при кике (ЛС закрыты или бот заблокирован).")
        except Exception as dm_error:
             logger.error(f"Ошибка при отправке DM пользователю {member} при кике: {dm_error}")

        # Выполняем кик
        await member.kick(reason=f"Кикнут {ctx.author.name}: {reason}")

        # Отправляем подтверждение в канал
        await safe_send(
            ctx,
            f"Пользователь {member.mention} ({member.name}) был кикнут. Причина: {reason}"
        )

        logger.info(f"Администратор {ctx.author} кикнул {member} по причине: {reason}")

    @commands.hybrid_command(
        name="restart",
        description="Перезапускает бота (только для владельца)"
    )
    @commands.is_owner()
    @command_error_handler
    async def restart(self, ctx: commands.Context):
        """
        (Только для владельца) Инициирует перезапуск бота.

        Предполагается, что бот запущен через systemd сервис с именем 'discord-bot'
        и у пользователя бота есть права на выполнение `sudo systemctl restart discord-bot` без пароля.
        Создает и запускает временный скрипт `restart.sh` для выполнения перезапуска.
        """
        is_slash = hasattr(ctx, 'interaction') and ctx.interaction is not None
        if is_slash:
            await ctx.defer(ephemeral=True)

        message_content = "🔄 Перезапуск бота..."
        response_message = None
        if is_slash:
            await ctx.send(message_content, ephemeral=True)
        else:
            response_message = await ctx.send(message_content)

        script_path = "restart.sh"
        service_name = "discord-bot" # Имя systemd сервиса (изменить при необходимости)
        try:
            with open(script_path, "w") as f:
                f.write("#!/bin/bash\n")
                f.write("sleep 1\n") # Небольшая задержка
                f.write(f"sudo systemctl restart {service_name}\n") # Команда перезапуска сервиса

            os.chmod(script_path, 0o755) # Даем скрипту права на выполнение

            logger.info(f"Запуск скрипта перезапуска: {script_path}")
            subprocess.Popen(["bash", script_path], start_new_session=True)

            logger.info("Закрытие текущего экземпляра бота...")
            await asyncio.sleep(0.5)
            await self.bot.close() # Завершаем работу текущего процесса бота

        except Exception as e:
            logger.error(f"Ошибка при попытке перезапуска: {e}")
            error_message = f"❌ Ошибка при перезапуске: ```{e}```"
            # Пытаемся отредактировать исходное сообщение об ошибке или отправить новое
            if is_slash:
                await ctx.edit_original_response(content=error_message)
            elif response_message:
                 try:
                     await response_message.edit(content=error_message)
                 except discord.NotFound: # Если исходное сообщение было удалено
                     await ctx.send(error_message)
            else: # Если не удалось отправить исходное сообщение
                 await ctx.send(error_message)

async def setup(bot: commands.Bot):
    """
    Добавляет ког Admin к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(AdminCog(bot))
    logger.info("Ког AdminCog успешно загружен.")
