"""
Модуль для унифицированной обработки ошибок в командах бота.

Этот модуль предоставляет декоратор и вспомогательные функции для обработки
ошибок в командах Discord бота. Он обеспечивает:
- Единообразную обработку исключений в командах
- Безопасную отправку сообщений об ошибках пользователям
- Логирование ошибок с контекстом
- Поддержку как обычных команд, так и slash-команд
"""

import functools
import logging
from typing import Any, Callable, Optional, TypeVar, cast

import discord
from discord.ext import commands

logger: logging.Logger = logging.getLogger("bot.utils.error_handler")

# Определяем типы для декоратора
F = TypeVar("F", bound=Callable[..., Any])


def command_error_handler(func: F) -> F:
    """
    Декоратор для унифицированной обработки ошибок в командах.

    Оборачивает функцию команды в try-except блок, который перехватывает
    все исключения, логирует их и отправляет пользователю сообщение об ошибке.
    Поддерживает как обычные команды, так и slash-команды.

    Args:
        func: Функция команды для обработки ошибок.

    Returns:
        Обернутая функция с обработкой ошибок.

    Examples:
        @commands.hybrid_command()
        @command_error_handler
        async def my_command(self, ctx):
            # Код команды
            pass
    """

    @functools.wraps(func)
    async def wrapper(self: Any, ctx: commands.Context, *args: Any, **kwargs: Any) -> Any:
        """
        Обертка для функции команды с обработкой ошибок.

        Args:
            self: Экземпляр кога.
            ctx: Контекст команды.
            *args: Позиционные аргументы команды.
            **kwargs: Именованные аргументы команды.

        Returns:
            Результат выполнения оригинальной функции или None в случае ошибки.

        Raises:
            Не выбрасывает исключений, все они перехватываются и обрабатываются.
        """
        try:
            return await func(self, ctx, *args, **kwargs)
        except discord.NotFound as e:
            # Если это ошибка "Unknown interaction" или "Unknown Message", просто логируем
            error_str = str(e).lower()
            if "unknown message" in error_str or "unknown interaction" in error_str:
                logger.info(f"Взаимодействие не найдено при выполнении {func.__name__}: {e}")
                return

            # Для других ошибок NotFound пытаемся отправить сообщение
            logger.error(f"Ошибка 'Not Found' в команде {func.__name__}: {e}", exc_info=True)
            await safe_send_error(ctx, e)

        except Exception as e:
            logger.error(f"Ошибка в команде {func.__name__}: {e}", exc_info=True)
            await safe_send_error(ctx, e)

    return cast(F, wrapper)


async def safe_send_error(ctx: commands.Context | discord.Interaction, error: Exception) -> None:
    """
    Вспомогательная функция для безопасной отправки сообщений об ошибках.

    Определяет тип команды (обычная или slash) и отправляет сообщение об ошибке
    соответствующим способом. Обрабатывает различные состояния взаимодействия
    для slash-команд.

    Args:
        ctx: Контекст команды (может быть Context или Interaction).
        error: Исключение, которое нужно отобразить пользователю.

    Returns:
        None
    """
    try:
        # Проверяем тип контекста и статус отложенного ответа
        if isinstance(ctx, discord.Interaction):
            # Для slash-команд
            interaction = ctx  # Теперь ctx это discord.Interaction
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Произошла ошибка: {error}", ephemeral=True
                )
            else:
                try:
                    await interaction.followup.send(f"Произошла ошибка: {error}", ephemeral=True)
                except discord.NotFound:
                    # Если взаимодействие/канал потеряны, логируем
                    if interaction.channel and isinstance(
                        interaction.channel, discord.abc.Messageable
                    ):
                        error_message = f"Произошла ошибка при выполнении команды: {error}"
                        await interaction.channel.send(error_message, delete_after=10)
                    else:
                        warning_message = (
                            "Не удалось отправить сообщение об ошибке в канал для взаимодействия "
                            f"{interaction.id}."
                        )
                        logger.warning(warning_message)
        elif isinstance(ctx, commands.Context):
            # Для обычных команд
            await ctx.send(f"Произошла ошибка: {error}")
        else:
            logger.error(f"Неизвестный тип контекста в safe_send_error: {type(ctx)}")
    except Exception as send_error:
        logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")


async def safe_send(
    ctx: commands.Context | discord.Interaction, content: str, **kwargs: Any
) -> Optional[discord.Message]:
    """
    Безопасно отправляет сообщение в зависимости от типа команды.

    Определяет тип команды (обычная или slash) и отправляет сообщение
    соответствующим способом. Поддерживает дополнительные параметры,
    такие как ephemeral для slash-команд и delete_after для обычных команд.

    Args:
        ctx: Контекст команды (может быть Context или Interaction).
        content: Текст сообщения для отправки.
        **kwargs: Дополнительные параметры для передачи в функцию отправки.
            - ephemeral: Видимо только автору (для slash-команд).
            - delete_after: Удалить сообщение через указанное время (для обычных команд).

    Returns:
        discord.Message: Отправленное сообщение (для обычных команд) или None (для slash-команд).
    """
    try:
        # delete_after поддерживается только у обычного ctx.send
        delete_after = kwargs.pop("delete_after", None)

        if isinstance(ctx, discord.Interaction):
            # Для slash-команд
            interaction = ctx  # Теперь ctx это discord.Interaction
            if not interaction.response.is_done():
                await interaction.response.send_message(content, **kwargs)
                return None  # WebhookMessage не возвращается или не используется
            else:
                # followup.send может вернуть WebhookMessage, но мы его не используем
                await interaction.followup.send(content, **kwargs)
                return None
        elif isinstance(ctx, commands.Context):
            # Для обычных команд
            message: Optional[discord.Message] = None  # Объявляем message здесь
            if delete_after is not None:
                message = await ctx.send(content, delete_after=delete_after, **kwargs)
                return message
            else:
                message = await ctx.send(content, **kwargs)
                return message
        else:
            logger.error(f"Неизвестный тип контекста в safe_send: {type(ctx)}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}", exc_info=True)
        return None
