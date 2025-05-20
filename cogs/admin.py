"""
Административный ког с командами для управления ботом и сервером.

Этот модуль содержит команды для администраторов сервера Discord, такие как:
- Очистка сообщений в каналах (с обходом ограничения в 14 дней)
- Исключение пользователей с сервера
- Перезапуск бота (только для владельца)

Команды имеют проверки прав доступа и защиту от злоупотреблений.
"""

import asyncio
import datetime
import logging
import subprocess
from typing import Dict, Optional, Tuple

import discord
from discord.ext import commands

from utils.error_handler import command_error_handler, safe_send

logger: logging.Logger = logging.getLogger("bot.cogs.admin")  # Используем иерархическое имя логгера


class AdminCog(commands.Cog):
    """
    Ког с административными командами для управления ботом и сервером.

    Предоставляет команды для модерации сервера, такие как очистка сообщений,
    исключение пользователей и перезапуск бота. Все команды имеют проверки
    прав доступа и защиту от злоупотреблений.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        Инициализирует административный ког.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot: commands.Bot = bot
        # Словарь для отслеживания времени последней очистки {channel_id: (timestamp, count)}
        # Используется для предотвращения спама командой clear
        self.recent_purges: Dict[int, Tuple[float, Optional[int]]] = {}

    async def _clear_messages_helper(
        self, ctx: commands.Context, count: int, user: Optional[discord.Member] = None
    ) -> int:
        """Вспомогательная функция для удаления сообщений, обходящая ограничение в 14 дней.

        Удаляет "новые" сообщения пачкой, "старые" - по одному.

        Args:
            ctx: Контекст команды.
            count: Желаемое количество сообщений для удаления.
            user: Если указан, удаляются только сообщения этого пользователя.

        Returns:
            int: Фактическое количество удаленных сообщений.
        """

        def check(msg: discord.Message) -> bool:
            """
            Проверяет, должно ли сообщение быть удалено.

            Args:
                msg: Сообщение для проверки.

            Returns:
                bool: True, если сообщение должно быть удалено, иначе False.
            """
            return user is None or msg.author == user

        # Discord API позволяет массово удалять только сообщения не старше 14 дней
        two_weeks_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)

        messages_to_delete = []
        # Собираем историю сообщений (берем с запасом, т.к. будем фильтровать)
        if isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):  # Проверка типа канала
            async for msg in ctx.channel.history(limit=count * 2):
                if check(msg):
                    messages_to_delete.append(msg)
                    if len(messages_to_delete) >= count:
                        break  # Набрали нужное количество
        else:
            # Канал не поддерживает историю или удаление сообщений
            logger.warning(
                f"Канал {ctx.channel.id} типа {type(ctx.channel)} "
                "не поддерживает удаление сообщений."
            )
            return 0

        if not messages_to_delete:  # Если нечего удалять
            return 0

        # Разделяем сообщения на "новые" (можно удалить пачкой) и "старые" (удаляем по одному)
        two_weeks_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)
        recent_messages = [msg for msg in messages_to_delete if msg.created_at > two_weeks_ago]
        old_messages = [msg for msg in messages_to_delete if msg.created_at <= two_weeks_ago]

        deleted_count = 0

        # Массовое удаление недавних сообщений
        if recent_messages and isinstance(
            ctx.channel, (discord.TextChannel, discord.Thread)
        ):  # Проверка типа канала
            try:
                # delete_messages не возвращает значение, всегда возвращает None
                await ctx.channel.delete_messages(recent_messages)
                # Считаем, что все сообщения были удалены успешно
                deleted_count += len(recent_messages)
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
                        logger.warning(
                            f"Не удалось удалить новое сообщение {msg.id} по одному: {e_single}"
                        )

        # Удаление старых сообщений по одному
        for msg in old_messages:
            try:
                await msg.delete()
                deleted_count += 1
                await asyncio.sleep(0.5)  # Небольшая задержка между удалениями старых сообщений
            except discord.NotFound:
                pass  # Сообщение уже удалено
            except Exception as e:
                logger.warning(f"Не удалось удалить старое сообщение {msg.id}: {e}")

        return deleted_count

    @commands.hybrid_command(description="Очистить сообщения в канале")
    @commands.has_permissions(manage_messages=True)
    @command_error_handler
    async def clear(
        self,
        ctx: commands.Context,
        count: int = 10,
        user: Optional[discord.Member] = None,
    ) -> None:
        """
        Очищает указанное количество сообщений из текущего канала.

        Можно указать пользователя, чьи сообщения нужно удалить.
        Обходит ограничение Discord API на удаление сообщений старше 14 дней.
        Есть защита от слишком частого использования команды.

        Args:
            ctx: Контекст команды.
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
            if last_count is not None and current_time - last_time < 10 and count > 10:
                await safe_send(
                    ctx,
                    (
                        f"Вы недавно удалили {last_count} сообщений. "
                        "Подождите немного перед новым массовым удалением."
                    ),
                    ephemeral=True,
                )
                return

        is_slash = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_slash:
            await ctx.defer(ephemeral=True)  # Отложенный ответ, видимый только автору

        # Запоминаем время и количество для защиты от спама
        self.recent_purges[channel_id] = (current_time, count)

        # Выполняем фактическое удаление
        deleted_count = await self._clear_messages_helper(ctx, count=count, user=user)

        # Формируем и отправляем сообщение о результате
        message = f"Удалено {deleted_count} сообщений"
        if user:
            message += f" пользователя {user.display_name}"

        # Отправляем подтверждение (эфемерное для slash, удаляемое через 5 сек для префиксных)
        await safe_send(
            ctx,
            message + ".",
            ephemeral=True if is_slash else False,
            delete_after=5 if not is_slash else None,
        )

        logger.info(
            (
                f"Администратор {ctx.author} удалил {deleted_count} сообщений "
                f"в канале {ctx.channel.name}"
            )
        )

    @commands.hybrid_command(description="Кикнуть пользователя с сервера")
    @commands.has_permissions(kick_members=True)
    @command_error_handler
    async def kick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "Причина не указана",
    ) -> None:
        """
        Кикает пользователя с сервера.

        Args:
            ctx: Контекст команды.
            member: Пользователь для кика (@упоминание или ID).
            reason: Причина кика (опционально).
        """
        # Проверка иерархии ролей: нельзя кикнуть пользователя с ролью выше или равной вашей
        if (
            member.top_role.position >= ctx.author.top_role.position
            and ctx.author.id != ctx.guild.owner_id
        ):
            await safe_send(
                ctx,
                "Вы не можете кикнуть участника с равной или более высокой ролью.",
                ephemeral=True,
            )
            return
        # Проверка иерархии ролей: бот не может кикнуть пользователя с ролью выше или равной своей
        if member.top_role.position >= ctx.guild.me.top_role.position:
            await safe_send(
                ctx, "У бота недостаточно прав для кика этого участника.", ephemeral=True
            )
            return

        # Пытаемся отправить личное сообщение пользователю о кике
        try:
            await member.send(f"Вы были кикнуты с сервера **{ctx.guild.name}**. Причина: {reason}")
        except discord.Forbidden:
            logger.warning(
                (
                    f"Не удалось отправить DM пользователю {member} "
                    "при кике (ЛС закрыты или бот заблокирован)."
                )
            )
        except Exception as dm_error:
            logger.error(f"Ошибка при отправке DM пользователю {member} при кике: {dm_error}")

        # Выполняем кик
        await member.kick(reason=f"Кикнут {ctx.author.name}: {reason}")

        # Отправляем подтверждение в канал
        await safe_send(
            ctx, f"Пользователь {member.mention} ({member.name}) был кикнут. Причина: {reason}"
        )

        logger.info(f"Администратор {ctx.author} кикнул {member} по причине: {reason}")

    @commands.hybrid_command(
        name="restart", description="Перезапускает бота (только для владельца)"
    )
    @commands.is_owner()
    @command_error_handler
    async def restart(self, ctx: commands.Context) -> None:
        """
        (Только для владельца) Инициирует перезапуск бота.

        Предполагается, что бот запущен через systemd user-сервис с именем
        'discord-bot.service' и у пользователя бота есть права на выполнение
        `systemctl --user restart discord-bot.service`.
        """
        is_slash = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_slash:
            await ctx.defer(ephemeral=True)

        message_content = "🔄 Перезапуск бота..."
        response_message = None
        if is_slash and ctx.interaction:
            await ctx.interaction.followup.send(
                message_content, ephemeral=True
            )  # Используем followup
        elif not is_slash:
            response_message = await ctx.send(message_content)
        else:  # Случай если is_slash True, но ctx.interaction почему-то None (маловероятно)
            await ctx.send(message_content, ephemeral=True)

        service_name = "discord-bot.service"  # Имя systemd user-сервиса
        restart_command = ["systemctl", "--user", "restart", service_name]
        try:
            logger.info(f"Отправка команды перезапуска: {' '.join(restart_command)}")
            subprocess.Popen(restart_command, start_new_session=True)

            logger.info("Закрытие текущего экземпляра бота...")
            await asyncio.sleep(0.5)
            await self.bot.close()  # Завершаем работу текущего процесса бота

        except Exception as e:
            logger.error(f"Ошибка при попытке перезапуска: {e}")
            error_message = f"❌ Ошибка при перезапуске: ```{e}```"
            # Пытаемся отредактировать исходное сообщение об ошибке или отправить новое
            if is_slash and ctx.interaction:
                await ctx.interaction.edit_original_response(content=error_message)
            elif response_message:
                try:
                    await response_message.edit(content=error_message)
                except discord.NotFound:
                    await ctx.send(error_message)
            else:
                await ctx.send(error_message)

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        logger.info(f"Ког {self.__class__.__name__} выгружен.")

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """
        Обрабатывает ошибки, возникающие при выполнении команд в этом коге.

        Args:
            ctx: Контекст команды, где произошла ошибка.
            error: Объект ошибки.
        """
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас нет прав для выполнения этой команды.", ephemeral=True)
        elif isinstance(error, commands.CommandInvokeError):
            logger.error(
                f"Ошибка при выполнении команды: {error.original}", exc_info=error.original
            )
            await ctx.send(f"Произошла ошибка: {error.original}", ephemeral=True)
        else:
            logger.error(f"Необработанная ошибка в команде: {error}", exc_info=error)
            await ctx.send(f"Произошла неизвестная ошибка: {error}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """
    Добавляет ког Admin к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(AdminCog(bot))
    logger.info("Ког AdminCog успешно загружен.")
