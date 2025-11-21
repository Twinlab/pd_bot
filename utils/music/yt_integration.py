"""Модуль для взаимодействия с yt-dlp для скачивания треков и поиска видео на YouTube."""

import asyncio
import logging
from typing import Any

import yt_dlp

from config import get_settings

from .config import PROXY_URL

# Создаем логгер с иерархическим именем
logger = logging.getLogger("bot.utils.music.yt_integration")


async def get_stream_info(url: str) -> dict[str, Any] | None:
    """
    Получает информацию о треке и URL аудиопотока с помощью yt-dlp без скачивания.

    Args:
        url: URL-адрес трека.

    Returns:
        Словарь с информацией о треке (включая 'url' для потока)
        в случае успеха, иначе None.

    Raises:
        yt_dlp.utils.DownloadError: Если происходит ошибка непосредственно при получении информации.
    """
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "auto",
        "source_address": "0.0.0.0",  # Обязательно для IPv4
        "proxy": PROXY_URL,
        "youtube_include_dash_manifest": False,
    }

    start_time = asyncio.get_event_loop().time()
    try:
        ytdl = yt_dlp.YoutubeDL(ydl_opts)
        info = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ytdl.extract_info(url, download=False)
        )
        extract_time = asyncio.get_event_loop().time() - start_time
        logger.info(f"Информация о потоке получена за {extract_time:.2f} секунд")

        if not info:
            logger.warning(f"yt-dlp вернул пустую информацию для {url}")
            return None

        # Если это плейлист, берем первый элемент
        if "entries" in info:
            if not info["entries"]:
                logger.warning(f"yt-dlp вернул пустой список 'entries' для {url}")
                return None
            info = info["entries"][0]

        # Проверяем, есть ли URL для потока
        if not info.get("url"):
            logger.error(f"Не удалось извлечь URL потока для {info.get('webpage_url')}")
            return None

        # Добавляем оригинальный URL для справки
        info["original_url"] = url
        result: dict[str, Any] = info
        return result

    except yt_dlp.utils.DownloadError as e:
        logger.warning(f"yt-dlp DownloadError при получении информации о потоке: {e}")
        raise
    except Exception as e:
        logger.error(
            f"Неожиданная ошибка при получении информации о потоке ({url}): {e}", exc_info=True
        )
        return None


async def search_youtube(query: str, max_results: int | None = None) -> list[dict[str, Any]] | None:
    """
    Ищет видео на YouTube по заданному запросу без фактического скачивания.

    Args:
        query: Поисковый запрос.
        max_results: Максимальное количество результатов для возврата.
                    Если None, используется значение из конфигурации.

    Returns:
        Список словарей, где каждый словарь содержит информацию о найденном видео,
        или None, если ничего не найдено или произошла ошибка.
    """
    # Получаем настройки
    settings = get_settings()
    if max_results is None:
        max_results = settings.music.yt_dlp.search_limit

    # Используем дополнительные настройки из конфига
    yt_dlp_config = settings.music.yt_dlp
    logger.info(f"Поиск на YouTube: '{query}' (max_results={max_results})")
    ydl_opts = {
        # Хотя скачивание не происходит, некоторые экстракторы могут требовать формат
        "format": "bestaudio",
        "skip_download": True,
        # Ограничивает количество извлекаемых элементов плейлиста/поиска
        "playlistend": max_results,
        "quiet": True,
        "no_warnings": True,
        "default_search": f"ytsearch{max_results}",
        "source_address": "0.0.0.0",
        "proxy": PROXY_URL,
        "socket_timeout": yt_dlp_config.socket_timeout,
        "retries": yt_dlp_config.retries,
        "geo_bypass": True,
        "geo_bypass_country": yt_dlp_config.geo_bypass_country,
        "logtostderr": False,
        "ignoreerrors": True,
        "skip_download_archive": True,
        "youtube_include_dash_manifest": False,
        # Используем 'extract_flat', чтобы получать только базовую информацию о видео.
        # Это значительно ускоряет поиск и снижает риск ошибок.
        "extract_flat": "in_playlist",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    try:
        ytdl = yt_dlp.YoutubeDL(ydl_opts)
        info = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ytdl.extract_info(query, download=False)
        )
        if not info or not info.get("entries"):
            logger.warning(f"Поиск на YouTube для '{query}' не вернул результатов.")
            return None
        valid_entries = []
        for entry in info["entries"]:
            if not isinstance(entry, dict):
                continue
            # С опцией 'extract_flat' yt-dlp возвращает только ID,
            # поэтому мы собираем URL вручную.
            if entry.get("id") and entry.get("ie_key") == "Youtube":
                entry["url"] = f"https://www.youtube.com/watch?v={entry['id']}"
                valid_entries.append(entry)
        logger.info(f"Найдено {len(valid_entries)} валидных результатов для '{query}'")
        return valid_entries
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError при поиске '{query}': {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при поиске на YouTube для '{query}': {e}", exc_info=True)
        return None
