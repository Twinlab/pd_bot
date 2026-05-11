"""Модуль для централизованной обработки ошибок."""

import functools
import logging
from collections.abc import Callable
from typing import Any, cast

import discord
from discord.ext import commands

logger = logging.getLogger("bot.utils.error_handler")

# Словарь с пользовательскими сообщениями для разных типов ошибок
ERROR_MESSAGES: dict[type, str] = {
    commands.MissingRequiredArgument: "Отсутствует обязательный аргумент: {error.param.name}",
    commands.BadArgument: "Неверный аргумент: {error}",
    commands.MissingPermissions: "У вас недостаточно прав для выполнения этой команды.",
    commands.BotMissingPermissions: "У бота недостаточно прав для выполнения этой команды.",
    commands.CommandOnCooldown: "Команда на перезарядке. Попробуйте через {error.retry_after:.1f} "
    "сек.",
    commands.NotOwner: "Эта команда доступна только владельцу бота.",
    commands.MemberNotFound: "Участник не найден: {error.argument}",
    commands.ChannelNotFound: "Канал не найден: {error.argument}",
    commands.RoleNotFound: "Роль не найдена: {error.argument}",
    commands.CommandNotFound: "Команда не найдена.",
    discord.Forbidden: "У бота нет прав для выполнения этого действия.",
    discord.NotFound: "Ресурс не найден: {error}",
    discord.HTTPException: "Ошибка Discord API: {error}",
    ValueError: "Ошибка значения: {error}",
    TypeError: "Ошибка типа: {error}",
    KeyError: "Ключ не найден: {error}",
    IndexError: "Индекс вне диапазона: {error}",
    FileNotFoundError: "Файл не найден: {error}",
    PermissionError: "Ошибка прав доступа: {error}",
    TimeoutError: "Превышено время ожидания: {error}",
    ConnectionError: "Ошибка подключения: {error}",
}


def command_error_handler[F: Callable[..., Any]](func: F) -> F:
    """
    Декоратор для обработки ошибок команд.

    Args:
        func: Функция команды.

    Returns:
        Декорированная функция.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, ctx: commands.Context, *args: Any, **kwargs: Any) -> Any:
        try:
            return await func(self, ctx, *args, **kwargs)
        except Exception as error:
            # Логируем ошибку
            logger.error(
                f"Ошибка в команде {ctx.command}: {error}",
                exc_info=True,
                extra={
                    "command": ctx.command.name if ctx.command else "unknown",
                    "author": f"{ctx.author} ({ctx.author.id})",
                    "guild": f"{ctx.guild} ({ctx.guild.id})" if ctx.guild else "DM",
                    "channel": f"{ctx.channel} ({ctx.channel.id})",
                    "user_message_content": (
                        ctx.message.content
                        if hasattr(ctx, "message") and ctx.message
                        else "No message"
                    ),
                },
            )

            # Получаем сообщение об ошибке
            error_message = get_error_message(error)

            # Отправляем сообщение об ошибке
            await safe_send_error(ctx, error_message)

            # Если это критическая ошибка, пересылаем её дальше
            if isinstance(error, (commands.CommandInvokeError, commands.HybridCommandError)):
                original = error.original
                if isinstance(original, (SystemExit, KeyboardInterrupt)):
                    raise original from None

            # Записываем метрики ошибки, если есть
            if hasattr(self.bot, "metrics"):
                self.bot.metrics.record_error(
                    command_name=ctx.command.name if ctx.command else "unknown",
                    error_type=type(error).__name__,
                    user_id=ctx.author.id,
                )

    return cast(F, wrapper)


def get_error_message(error: Exception) -> str:
    """
    Возвращает пользовательское сообщение об ошибке.

    Args:
        error: Объект ошибки.

    Returns:
        Сообщение об ошибке.
    """
    # Если это ошибка вызова команды, получаем оригинальную ошибку
    if isinstance(error, (commands.CommandInvokeError, commands.HybridCommandError)):
        error = error.original

    # Ищем сообщение в словаре ERROR_MESSAGES
    for error_type, message_template in ERROR_MESSAGES.items():
        if isinstance(error, error_type):
            try:
                return message_template.format(error=error)
            except Exception:
                return f"Произошла ошибка: {error}"

    # Если не нашли, возвращаем общее сообщение
    return f"Произошла непредвиденная ошибка: {error}"


async def safe_send(
    ctx: commands.Context | discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    ephemeral: bool = False,
    delete_after: float | None = None,
) -> discord.Message | None:
    """
    Безопасно отправляет сообщение, учитывая тип контекста (Context или Interaction).

    Args:
        ctx: Контекст команды или взаимодействие.
        content: Текст сообщения.
        embed: Эмбед для отправки.
        ephemeral: Отправить как эфемерное сообщение (только для Interaction).

    Returns:
        Отправленное сообщение или None в случае ошибки.
    """
    try:
        if isinstance(ctx, discord.Interaction):
            if ctx.response.is_done():
                # Используем cast для явного приведения типа
                followup_msg = cast(
                    discord.Message,
                    await ctx.followup.send(content=content, embed=embed, ephemeral=ephemeral),
                )
                return followup_msg
            else:
                await ctx.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
                # Используем cast для явного приведения типа
                response_msg = cast(discord.Message, await ctx.original_response())
                return response_msg
        else:
            return await ctx.send(content=content, embed=embed, delete_after=delete_after)
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}", exc_info=True)
        return None


async def safe_send_error(
    ctx: commands.Context | discord.Interaction, error_message: str
) -> discord.Message | None:
    """
    Безопасно отправляет сообщение об ошибке.

    Args:
        ctx: Контекст команды или взаимодействие.
        error_message: Сообщение об ошибке.

    Returns:
        Отправленное сообщение или None в случае ошибки.
    """
    embed = discord.Embed(
        title="❌ Ошибка",
        description=error_message,
        color=discord.Color.red(),
    )
    return await safe_send(ctx, embed=embed, ephemeral=True)
