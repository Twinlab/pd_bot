"""Модуль для взаимодействия с yt-dlp для музыкального плеера V2."""

import asyncio
import logging
from typing import Any, cast

import yt_dlp

from .errors import TrackError

logger = logging.getLogger("bot.utils.music_v2.youtube")

YDL_OPTS_BASE = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}


async def get_track_info(url: str, loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
    """Получает информацию о треке с помощью yt-dlp, не скачивая его.

    Использует 'extract_flat' для быстрого получения метаданных.

    Args:
        url: URL-адрес трека.
        loop: Цикл событий asyncio для запуска в executor.

    Returns:
        Словарь с информацией о треке.

    Raises:
        TrackError: Если не удалось получить информацию о треке.
    """
    opts = YDL_OPTS_BASE.copy()
    opts["extract_flat"] = "in_playlist"  # Получаем только метаданные

    try:
        ytdl = yt_dlp.YoutubeDL(opts)
        info = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

        if not info:
            raise TrackError("Не удалось получить информацию о треке (yt-dlp вернул None).")

        # Если это плейлист, берем первый элемент
        if "entries" in info:
            if not info["entries"]:
                raise TrackError("Поиск по ссылке вернул пустой плейлист.")
            info = info["entries"][0]

        return cast(dict[str, Any], info)

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Ошибка yt-dlp при получении информации о треке {url}: {e}")
        raise TrackError(
            f"Не удалось обработать ссылку. Возможно, она неверна или видео недоступно. ({e.msg})"
        ) from e
    except Exception as e:
        logger.error(
            f"Неожиданная ошибка при получении информации о треке {url}: {e}", exc_info=True
        )
        raise TrackError("Произошла непредвиденная ошибка при запросе информации о треке.") from e
