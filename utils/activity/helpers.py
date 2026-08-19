"""Вспомогательные функции для модуля отслеживания активности.

Этот модуль содержит утилитарные функции, используемые в системе отслеживания
активности пользователей на сервере Discord. Включает функции для фильтрации
ботов и форматирования времени.
"""

import discord

_APPLICATION_NAMES = frozenset({"minecraft bot"})
_APPLICATION_ROLE_NAMES = frozenset({"bot", "app", "application"})


def is_application(member: discord.Member) -> bool:
    """Проверяет, является ли участник ботом или приложением на основе имени или ролей.

    Используется для фильтрации ботов при отслеживании активности.

    Args:
        member: Объект discord.Member для проверки.

    Returns:
        True, если участник вероятно является ботом/приложением, False в противном случае.
    """
    if member.bot:
        return True

    if member.name.casefold() in _APPLICATION_NAMES:
        return True

    return any(role.name.casefold() in _APPLICATION_ROLE_NAMES for role in member.roles)


def format_time_short(seconds: int) -> str:
    """Форматирует время в секундах в короткую строку (например, "1h 5m").

    Args:
        seconds: Общее количество секунд.

    Returns:
        Короткая отформатированная строка, представляющая продолжительность.
    """
    if seconds <= 0:
        return "0m"

    if seconds < 60:
        return "<1m"

    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if hours > 0:
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    return f"{minutes}m"
