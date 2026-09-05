"""Проверки каналов перед публичной перепубликацией сообщений."""

import discord


def public_message_channel_ids(guild: discord.Guild | None) -> set[int]:
    """Возвращает ID общедоступных каналов и известных публичных веток.

    Args:
        guild: Сервер, из которого разрешено брать сообщения.

    Returns:
        Каналы с доступной всем историей, без ограничений для отдельных ролей
        или участников. Неизвестные и приватные ветки не включаются.
    """
    if guild is None:
        return set()

    channel_ids: set[int] = set()
    for channel in guild.channels:
        permissions = channel.permissions_for(guild.default_role)
        if not permissions.view_channel or not permissions.read_message_history:
            continue
        # Открытый @everyone не отменяет запрет для отдельной роли или участника.
        if any(
            overwrite.view_channel is False or overwrite.read_message_history is False
            for overwrite in channel.overwrites.values()
        ):
            continue
        channel_ids.add(channel.id)

    channel_ids.update(
        thread.id
        for thread in guild.threads
        if not thread.is_private() and thread.parent_id in channel_ids
    )
    return channel_ids
