"""Модуль для взаимодействия с yt-dlp для скачивания треков и поиска видео на YouTube."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yt_dlp

from .config import DOWNLOADS_DIR, PROXY_URL, YDL_OPTS_BASE

# Создаем логгер с иерархическим именем
logger = logging.getLogger("bot.utils.music.yt_integration")


async def download_track(url: str) -> Optional[Dict[str, Any]]:
    """
    Скачивает трек с помощью yt-dlp и возвращает информацию о нем.

    Args:
        url: URL-адрес трека для скачивания.

    Returns:
        Словарь с информацией о треке (включая 'filepath' к скачанному файлу)
        в случае успеха, иначе None.

    Raises:
        yt_dlp.utils.DownloadError: Если происходит ошибка непосредственно при скачивании yt-dlp.
                                   Другие ошибки логируются и возвращается None.
    """
    ydl_opts = YDL_OPTS_BASE.copy()
    if "youtube.com" in url or "youtu.be" in url:
        logger.info("Обнаружена ссылка YouTube, применяем оптимизированные настройки")
        ydl_opts.update(
            {
                "format": "bestaudio[ext=webm]/bestaudio/best",
                "youtube_include_dash_manifest": False,
            }
        )
    start_time = asyncio.get_event_loop().time()
    try:
        ytdl = yt_dlp.YoutubeDL(ydl_opts)
        info = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ytdl.extract_info(url, download=True)
        )
        download_time = asyncio.get_event_loop().time() - start_time
        logger.info(f"Скачивание завершено за {download_time:.2f} секунд")
        if not info:
            logger.warning(f"yt-dlp вернул пустую информацию для {url}")
            return None
        if "entries" in info:
            if not info["entries"]:
                logger.warning(f"yt-dlp вернул пустой список 'entries' для {url}")
                return None
            info = info["entries"][0]
            if not info:
                logger.warning(f"yt-dlp вернул None в 'entries' для {url}")
                return None
        try:
            expected_base = ytdl.prepare_filename(info).rsplit(".", 1)[0]
        except Exception:
            extractor = info.get("extractor_key", "unknown").lower()
            track_id = info.get("id", "unknown_id")
            title = info.get("title", "unknown_title")
            safe_title = "".join(c if c.isalnum() or c in (" ", "_", "-") else "_" for c in title)[
                :100
            ]
            expected_base = str(DOWNLOADS_DIR / f"{extractor}-{track_id}-{safe_title}")

        # Безопасное получение предпочтительного расширения
        preferred_ext = ".mp3"  # Расширение по умолчанию
        postprocessors = ydl_opts.get("postprocessors")
        if postprocessors and len(postprocessors) > 0:
            first_processor = postprocessors[0]  # type: ignore
            if isinstance(first_processor, dict):
                preferred_ext = "." + first_processor.get("preferredcodec", "mp3")

        filepath_obj = Path(expected_base + preferred_ext)
        if not filepath_obj.exists():
            logger.warning(
                f"Файл {filepath_obj} не найден. Ищем с помощью glob: {Path(expected_base).name}.*"
            )
            # DOWNLOADS_DIR это Path объект из config
            # expected_base может быть полным путем, извлекаем только имя файла для glob
            search_pattern = f"{Path(expected_base).name}.*"
            found_files = list(DOWNLOADS_DIR.glob(search_pattern))

            if found_files:
                # Преобразуем Path объекты в строки для endswith и для filepath
                audio_files = [
                    str(f)
                    for f in found_files
                    if str(f)
                    .lower()
                    .endswith((".opus", ".mp3", ".ogg", ".m4a", ".aac", ".wav", ".flac"))
                ]
                if audio_files:
                    filepath_obj = Path(audio_files[0])
                    logger.info(f"Найден аудио файл через glob: {filepath_obj}")
                else:
                    filepath_obj = Path(
                        str(found_files[0])
                    )  # Берем первый найденный, если аудио нет
                    logger.warning(
                        (
                            "Не удалось найти аудио расширение, "
                            f"используем первое совпадение: {filepath_obj}"
                        )
                    )
            else:
                logger.error(
                    (
                        f"Не удалось найти скачанный файл по шаблону: {search_pattern} "
                        f"в {DOWNLOADS_DIR}"
                    )
                )
                return None

        info["filepath"] = str(filepath_obj)  # Сохраняем как строку, если так ожидается дальше
        result: Dict[str, Any] = info
        return result
    except yt_dlp.utils.DownloadError as e:
        logger.warning(f"yt-dlp DownloadError при скачивании: {e}")
        raise
    except Exception as e:
        logger.error(f"Неожиданная ошибка при скачивании трека ({url}): {e}", exc_info=True)
        return None


async def search_youtube(query: str, max_results: int = 10) -> Optional[List[Dict[str, Any]]]:
    """
    Ищет видео на YouTube по заданному запросу без фактического скачивания.

    Args:
        query: Поисковый запрос.
        max_results: Максимальное количество результатов для возврата.

    Returns:
        Список словарей, где каждый словарь содержит информацию о найденном видео,
        или None, если ничего не найдено или произошла ошибка.
    """
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
        "socket_timeout": 5,
        "retries": 1,
        "geo_bypass": True,
        "geo_bypass_country": YDL_OPTS_BASE.get(
            "geo_bypass_country", "RU"
        ),  # Используем 'RU' как значение по умолчанию
        "logtostderr": False,
        "ignoreerrors": True,
        "skip_download_archive": True,
        "youtube_include_dash_manifest": False,
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
            # yt-dlp >=2023.03.04 для ytsearch с extract_flat=True
            # не возвращает 'url', только 'id' и 'ie_key'
            if entry.get("url"):
                valid_entries.append(entry)
            elif entry.get("id") and entry.get("ie_key") == "Youtube":
                entry["url"] = f"https://www.youtube.com/watch?v={entry['id']}"
                valid_entries.append(entry)
        logger.info(f"Найдено {len(valid_entries)} результатов для '{query}'")
        return valid_entries
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError при поиске '{query}': {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при поиске на YouTube для '{query}': {e}", exc_info=True)
        return None
