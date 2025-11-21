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

import discord
from discord.ext import commands

from config import get_settings
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
        self.recent_purges: dict[int, tuple[float, int | None]] = {}

    async def _clear_messages_helper(
        self, ctx: commands.Context, count: int, user: discord.Member | None = None
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

        # Discord API позволяет массово удалять только сообщения не старше N дней
        settings = get_settings()
        days_limit = settings.limits.discord_api_days_limit
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            days=days_limit
        )

        messages_to_delete = []
        # Собираем историю сообщений (берем с запасом, т.к. будем фильтровать)
        if isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):  # Проверка типа канала
            async for msg in ctx.channel.history(limit=count * settings.limits.history_multiplier):
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
        recent_messages = [msg for msg in messages_to_delete if msg.created_at > cutoff_date]
        old_messages = [msg for msg in messages_to_delete if msg.created_at <= cutoff_date]

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
                await asyncio.sleep(
                    settings.timeouts.old_message_delete_delay
                )  # Задержка между удалениями старых сообщений
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
        user: discord.Member | None = None,
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
        settings = get_settings()
        if not (settings.limits.purge_min_count <= count <= settings.limits.purge_max_count):
            message = (
                f"Количество сообщений должно быть от {settings.limits.purge_min_count} "
                f"до {settings.limits.purge_max_count}."
            )
            await safe_send(ctx, message, ephemeral=True)
            return

        # Защита от спама командой clear
        channel_id = ctx.channel.id
        current_time = datetime.datetime.now().timestamp()

        if channel_id in self.recent_purges:
            last_time, last_count = self.recent_purges[channel_id]
            # Блокируем повторный вызов с count > threshold, если прошло < purge_rate_limit секунд
            if (
                last_count is not None
                and current_time - last_time < settings.timeouts.purge_rate_limit
                and count > settings.timeouts.admin_purge_threshold
            ):
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
        message = settings.messages.success["purge_complete"].format(count=deleted_count)
        if user:
            message += f" пользователя {user.display_name}"

        # Отправляем подтверждение (эфемерное для slash, удаляемое через 5 сек для префиксных)
        await safe_send(
            ctx,
            message + ".",
            ephemeral=True if is_slash else False,
            delete_after=settings.timeouts.admin_purge_delete_after if not is_slash else None,
        )

        logger.info(

                f"Администратор {ctx.author} удалил {deleted_count} сообщений "
                f"в канале {ctx.channel.name}"

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

                    f"Не удалось отправить DM пользователю {member} "
                    "при кике (ЛС закрыты или бот заблокирован)."

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

        В среде Docker это просто завершает процесс, а Docker (restart: unless-stopped)
        автоматически запустит его снова.
        """
        is_slash = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_slash:
            await ctx.defer(ephemeral=True)

        settings = get_settings()
        message_content = settings.messages.success["restart_initiated"]

        if is_slash and ctx.interaction:
            await ctx.interaction.followup.send(message_content, ephemeral=True)
        else:
            await ctx.send(message_content)

        logger.info("Получена команда перезапуска. Завершаем работу...")
        await asyncio.sleep(1) # Даем время на отправку сообщения
        await self.bot.close()

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
