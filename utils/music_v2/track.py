"""Модуль, содержащий класс Track для музыкального плеера V2."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import discord

logger = logging.getLogger("bot.utils.music_v2.track")


class Track:
    """Представляет один музыкальный трек."""

    def __init__(self, info: dict[str, Any], requester: discord.Member) -> None:
        """Инициализирует объект трека.

        Args:
            info: Словарь с информацией о треке, полученный от yt-dlp.
            requester: Участник Discord, запросивший трек.
        """
        self.url: str = info.get("webpage_url", "")
        self.title: str = info.get("title", "Неизвестное название")
        self.duration: int = info.get("duration", 0)
        self.thumbnail: str | None = info.get("thumbnail")
        self.uploader: str | None = info.get("uploader")
        self.requester: discord.Member = requester
        self.stream_url: str | None = info.get("url")  # Может быть None изначально

    def __str__(self) -> str:
        """Возвращает строковое представление трека."""
        return f"{self.title} ({self.format_duration()})"

    def format_duration(self) -> str:
        """Форматирует длительность трека в MM:SS или HH:MM:SS."""
        if self.duration <= 0:
            return "00:00"

        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
