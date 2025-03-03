import logging
import discord

logger = logging.getLogger("bot")

def is_slash_command(ctx):
    """Проверяет, является ли команда slash-командой"""
    return hasattr(ctx, 'interaction') and ctx.interaction is not None

async def safe_send(ctx, content, **kwargs):
    """Безопасно отправляет сообщение в зависимости от типа команды"""
    try:
        if is_slash_command(ctx):
            # Для slash-команд
            if not ctx.interaction.response.is_done():
                await ctx.respond(content, **kwargs)
            else:
                await ctx.followup.send(content, **kwargs)
        else:
            # Для обычных команд
            await ctx.send(content, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")
