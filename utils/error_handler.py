"""Модуль для централизованной обработки ошибок."""

import functools
import logging
from collections.abc import Callable
from typing import Any, cast

import discord
from discord import app_commands
from discord.ext import commands

from utils.ui import colors

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
    app_commands.MissingPermissions: "У вас недостаточно прав для выполнения этой команды.",
    app_commands.BotMissingPermissions: "У бота недостаточно прав для выполнения этой команды.",
    app_commands.CommandOnCooldown: "Команда на перезарядке. Попробуйте через "
    "{error.retry_after:.1f} сек.",
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
    """Декоратор: ловит исключения внутри тела команды, логирует и отвечает пользователю.

    Семантика подобрана так, чтобы НЕ дублировать работу глобального
    ``on_command_error`` из ``handlers/events.py``:

    - Ошибки до входа в тело (parsing/check/cooldown) сюда не доходят —
      их ловит ``on_command_error``.
    - Ошибки внутри тела ловятся здесь, логируются со стеком, юзер получает
      одно дружелюбное сообщение, исключение **проглатывается**. Иначе
      discord.py обернёт его в ``CommandInvokeError`` и вторично дёрнет
      ``on_command_error``, дав двойной лог и второй embed в чат.
    - ``SystemExit`` / ``KeyboardInterrupt`` всё равно пробрасываем —
      ими завершают процесс.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, ctx: commands.Context, *args: Any, **kwargs: Any) -> Any:
        try:
            return await func(self, ctx, *args, **kwargs)
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as error:
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

            await safe_send_error(ctx, get_error_message(error))

            if hasattr(self.bot, "metrics"):
                self.bot.metrics.record_error(
                    command_name=ctx.command.name if ctx.command else "unknown",
                    error_type=type(error).__name__,
                    user_id=ctx.author.id,
                )

            return None

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
    if isinstance(
        error,
        (
            commands.CommandInvokeError,
            commands.HybridCommandError,
            app_commands.CommandInvokeError,
        ),
    ):
        error = error.original

    # Ищем сообщение в словаре ERROR_MESSAGES
    for error_type, message_template in ERROR_MESSAGES.items():
        if isinstance(error, error_type):
            try:
                return message_template.format(error=error)
            except Exception:
                return "Произошла ошибка. Попробуйте позже."

    return "Произошла непредвиденная ошибка. Попробуйте позже."


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
            # ``ephemeral`` для prefix-команд discord.py молча игнорирует, а для
            # hybrid-слэша делает ответ эфемерным — поэтому пробрасываем всегда.
            return await ctx.send(
                content=content, embed=embed, delete_after=delete_after, ephemeral=ephemeral
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}", exc_info=True)
        return None


# Штатные ошибки app-команд: пользователю шлём текст, но НЕ валим стек в лог.
_KNOWN_APP_ERRORS = (
    app_commands.CheckFailure,
    app_commands.CommandOnCooldown,
    app_commands.TransformerError,
    app_commands.CommandNotFound,
)


async def handle_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    """Глобальный обработчик ошибок slash-команд (``CommandTree.on_error``).

    Незнакомые баги логируются со стеком; пользователю в любом случае уходит
    эфемерный embed с дружелюбным текстом из :data:`ERROR_MESSAGES`. Отвечаем
    через ``followup``, если интеракция уже была отвечена/отложена.
    """
    if not isinstance(error, _KNOWN_APP_ERRORS):
        command_name = interaction.command.name if interaction.command else "unknown"
        logger.error(
            f"Необработанная ошибка в slash-команде '{command_name}': {error}",
            exc_info=(type(error), error, error.__traceback__),
        )

    embed = discord.Embed(
        title="❌ Ошибка",
        description=get_error_message(error),
        color=colors.ERROR,
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException as e:
        logger.error(f"Не удалось отправить сообщение об ошибке slash-команды: {e}")


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
        color=colors.ERROR,
    )
    return await safe_send(ctx, embed=embed, ephemeral=True)
