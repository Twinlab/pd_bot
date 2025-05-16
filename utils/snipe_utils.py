"""
Утилиты для функционала "снайпа" (просмотра удаленных сообщений).

Этот модуль предоставляет функции для сохранения удаленных сообщений в кэш
и их последующего отображения по запросу пользователя. Поддерживает сохранение
текста сообщений, вложений и метаданных.
"""

import logging
from typing import Any, Dict

import discord
from discord.ext import commands

logger = logging.getLogger("bot.utils.snipe_utils")

# Кэш для хранения удаленных сообщений
snipe_cache: Dict[str, Dict[str, Any]] = {}


async def save_deleted_message(message: discord.Message) -> None:
    """
    Сохраняет удаленное сообщение для команды snipe.

    Сохраняет текст сообщения, информацию об авторе, временную метку
    и данные о вложениях (если есть). Игнорирует сообщения от ботов
    и сообщения без содержимого.

    Args:
        message: Удаленное сообщение (discord.Message)
    """
    try:
        # Игнорируем сообщения от ботов
        if message.author.bot:
            return

        # Проверяем, есть ли содержимое или вложения для сохранения
        has_content = bool(message.content)
        has_attachments = bool(message.attachments)

        # Если нет ни текста, ни вложений, игнорируем
        if not has_content and not has_attachments:
            return

        # Сохраняем информацию о вложениях
        attachments_data = []
        if has_attachments:
            for attachment in message.attachments:
                attachments_data.append(
                    {
                        "url": attachment.url,
                        "filename": attachment.filename,
                        "content_type": attachment.content_type,
                        "size": attachment.size,
                        "width": getattr(attachment, "width", None),
                        "height": getattr(attachment, "height", None),
                        "is_image": attachment.content_type
                        and attachment.content_type.startswith("image/"),
                    }
                )

        # Сохраняем информацию о сообщении
        channel_id = str(message.channel.id)
        snipe_cache[channel_id] = {
            "content": message.content,
            "author_name": message.author.display_name,
            "author_avatar": (
                message.author.avatar.url
                if message.author.avatar
                else message.author.default_avatar.url
            ),
            "timestamp": message.created_at,
            "has_attachments": has_attachments,
            "attachments": attachments_data,
        }
    except Exception as e:
        logger.error(f"Ошибка при сохранении удаленного сообщения: {e}", exc_info=True)


async def show_sniped_message(ctx: commands.Context) -> None:
    """
    Показывает последнее удаленное сообщение в канале.

    Создает и отправляет эмбед с информацией о последнем удаленном сообщении
    в текущем канале, включая текст, вложения и метаданные. Если удаленных
    сообщений нет, отправляет соответствующее уведомление.

    Args:
        ctx: Контекст команды (discord.ext.commands.Context)
    """
    try:
        channel_id = str(ctx.channel.id)

        if channel_id not in snipe_cache:
            await ctx.send("Нет удаленных сообщений для восстановления.")
            return

        snipe_data = snipe_cache[channel_id]

        # Создаем базовый эмбед
        embed = discord.Embed(color=discord.Color.red(), timestamp=snipe_data["timestamp"])

        # Добавляем содержимое, если оно есть
        if snipe_data["content"]:
            embed.description = snipe_data["content"]

        # Устанавливаем автора
        embed.set_author(name=snipe_data["author_name"], icon_url=snipe_data["author_avatar"])

        # Добавляем вложения, если они есть
        if snipe_data.get("has_attachments", False) and snipe_data.get("attachments"):
            attachments = snipe_data["attachments"]

            # Если сообщение было только с изображением без текста
            if (
                not snipe_data["content"]
                and len(attachments) == 1
                and attachments[0].get("is_image")
            ):
                embed.description = "*Сообщение содержало только изображение*"

            # Добавляем информацию о вложениях
            attachment_info = []
            for i, attachment in enumerate(attachments):
                if attachment.get("content_type"):
                    type_info = f"({attachment['content_type']})"
                else:
                    type_info = ""

                size_info = f"{attachment['size'] / 1024:.1f} KB" if attachment.get("size") else ""
                attachment_info.append(
                    f"[{attachment['filename']}]({attachment['url']}) {type_info} {size_info}"
                )

            if attachment_info:
                embed.add_field(name="Вложения", value="\n".join(attachment_info), inline=False)

            # Устанавливаем первое изображение как картинку в эмбеде
            for attachment in attachments:
                if attachment.get("is_image"):
                    embed.set_image(url=attachment["url"])
                    break

        embed.set_footer(text="Сообщение было удалено")

        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Ошибка при отображении удаленного сообщения: {e}", exc_info=True)
        await ctx.send(f"Произошла ошибка при отображении удаленного сообщения: {e}")
