"""Логика определения «реальной» голосовой активности.

Точное «говорит/молчит» через voice receive по gateway в discord.py недоступно,
поэтому опираемся на voice-state: AFK-канал, заглушка на приём (deaf) и одиночество
в канале. Чистая функция вынесена отдельно от кога ради тестируемости.
"""

import discord


def is_active_voice_state(
    *,
    channel_id: int | None,
    afk_channel_id: int | None,
    self_deaf: bool,
    deaf: bool,
    self_mute: bool,
    mute: bool,
    human_count: int,
    count_while_muted: bool,
    min_humans: int,
) -> bool:
    """Возвращает True, если голосовое время пользователя нужно засчитывать.

    Args:
        channel_id: ID текущего голосового канала (None — не в войсе).
        afk_channel_id: ID AFK-канала сервера (None — не настроен).
        self_deaf: Пользователь сам заглушил звук.
        deaf: Пользователь заглушён сервером.
        self_mute: Пользователь сам выключил микрофон.
        mute: Пользователь замьючен сервером.
        human_count: Сколько живых (не-бот) участников в канале, включая самого юзера.
        count_while_muted: Засчитывать ли время с выключенным микрофоном.
        min_humans: Минимум живых участников в канале для зачёта.

    Returns:
        True, если время идёт в зачёт.
    """
    if channel_id is None:
        return False
    if afk_channel_id is not None and channel_id == afk_channel_id:
        return False
    # Деаф = человек не слушает = реально афк.
    if self_deaf or deaf:
        return False
    if not count_while_muted and (self_mute or mute):
        return False
    if human_count < min_humans:
        return False
    return True


def count_humans(channel: discord.VoiceChannel | discord.StageChannel | None) -> int:
    """Считает живых (не-бот) участников в голосовом канале."""
    if channel is None:
        return 0
    return sum(1 for m in channel.members if not m.bot)


def member_is_active(
    member: discord.Member,
    *,
    count_while_muted: bool,
    min_humans: int,
) -> bool:
    """Обёртка над :func:`is_active_voice_state` для discord.Member.

    Берёт AFK-канал из гильдии и считает живых участников канала самостоятельно.
    """
    voice = member.voice
    if voice is None or voice.channel is None:
        return False

    afk_channel = member.guild.afk_channel
    return is_active_voice_state(
        channel_id=voice.channel.id,
        afk_channel_id=afk_channel.id if afk_channel else None,
        self_deaf=bool(voice.self_deaf),
        deaf=bool(voice.deaf),
        self_mute=bool(voice.self_mute),
        mute=bool(voice.mute),
        human_count=count_humans(voice.channel),
        count_while_muted=count_while_muted,
        min_humans=min_humans,
    )
