"""Вспомогательные функции для модуля отслеживания активности.

Этот модуль содержит утилитарные функции, используемые в системе отслеживания
активности пользователей на сервере Discord. Включает функции для фильтрации
ботов и форматирования времени.
"""

import discord


# TODO: В будущем может потребоваться доступ к конфигурации бота или ролям.
# Пока функция самодостаточна.
def is_application(member: discord.Member) -> bool:
    """Проверяет, является ли участник ботом или приложением на основе имени или ролей.

    Используется для фильтрации ботов при отслеживании активности.

    Args:
        member: Объект discord.Member для проверки.

    Returns:
        True, если участник вероятно является ботом/приложением, False в противном случае.
    """
    # Распространенные имена ботов (можно расширить)
    app_names = ["minecraft bot"]
    if member.name in app_names:
        return True

    # Распространенные названия ролей, указывающие на бота
    app_role_names = ["bot", "app", "application"]
    if any(role.name.lower() in app_role_names for role in member.roles):
        return True

    # Проверка официального флага бота
    if member.bot:
        return True

    return False


def format_time_short(seconds: int) -> str:
    """Форматирует время в секундах в короткую строку (например, "1h 5m").

    Args:
        seconds: Общее количество секунд.

    Returns:
        Короткая отформатированная строка, представляющая продолжительность.
    """
    if seconds <= 0:
        return "0m"  # Возвращаем "0m", если время нулевое или отрицательное

    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if hours > 0:
        if minutes > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{hours}h"
    else:
        # Всегда показываем минуты, даже если 0 и часы равны 0 (например, для ввода 30 секунд)
        return f"{minutes}m"
