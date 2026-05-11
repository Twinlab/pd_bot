"""Конфигурация музыкального модуля.

Содержит палитру цветов для эмбедов и общий логгер для всех файлов модуля.
Параметры подключения к Lavalink читаются напрямую из ``config.get_settings()``
в момент использования — это позволяет переопределять их в тестах без
перезагрузки модуля.
"""

import logging

from config import get_settings

logger = logging.getLogger("bot.music")

# Цвета берём один раз — они не меняются между рестартами.
_settings = get_settings()
COLORS = {
    "DEFAULT": _settings.get_discord_color("default"),
    "ERROR": _settings.get_discord_color("error"),
    "SUCCESS": _settings.get_discord_color("success"),
    "INFO": _settings.get_discord_color("info"),
    "WARNING": _settings.get_discord_color("warning"),
}
