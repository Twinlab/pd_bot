import discord
import functools
import logging

logger = logging.getLogger("bot")

def command_error_handler(func):
    """Декоратор для унифицированной обработки ошибок в командах"""
    @functools.wraps(func)
    async def wrapper(self, ctx, *args, **kwargs):
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
    
    return wrapper

async def safe_send_error(ctx, error):
    """Вспомогательная функция для безопасной отправки сообщений об ошибках"""
    try:
        # Проверяем тип контекста и статус отложенного ответа
        if hasattr(ctx, 'interaction') and ctx.interaction:
            # Для slash-команд с активным взаимодействием
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.send_message(f"Произошла ошибка: {error}", ephemeral=True)
            else:
                try:
                    await ctx.interaction.followup.send(f"Произошла ошибка: {error}", ephemeral=True)
                except discord.NotFound:
                    # Если взаимодействие потеряно, пробуем отправить обычное сообщение
                    await ctx.channel.send(f"Произошла ошибка при выполнении команды: {error}", 
                                           delete_after=10)
        else:
            # Для обычных команд
            await ctx.send(f"Произошла ошибка: {error}")
    except Exception as send_error:
        logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")

async def safe_send(ctx, content, **kwargs):
    """Безопасно отправляет сообщение в зависимости от типа команды"""
    try:
        is_slash = hasattr(ctx, 'interaction') and ctx.interaction is not None

        # delete_after поддерживается только у обычного ctx.send
        delete_after = kwargs.pop("delete_after", None)

        if is_slash:
            # Для slash-команд
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.send_message(content, **kwargs)
            else:
                await ctx.interaction.followup.send(content, **kwargs)
        else:
            # Для обычных команд
            if delete_after is not None:
                await ctx.send(content, delete_after=delete_after, **kwargs)
            else:
                await ctx.send(content, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}", exc_info=True)
