import yt_dlp
import asyncio
import glob
import os
from typing import Optional, Dict, Any, List

from .config import logger, YDL_OPTS_BASE, PROXY_URL, DOWNLOADS_DIR

async def download_track(url: str) -> Optional[Dict[str, Any]]:
    """Скачивает трек с помощью yt-dlp и возвращает информацию."""
    ydl_opts = YDL_OPTS_BASE.copy()
    if 'youtube.com' in url or 'youtu.be' in url:
        logger.info(f"Обнаружена ссылка YouTube, применяем оптимизированные настройки")
        ydl_opts.update({
            'format': 'bestaudio[ext=webm]/bestaudio/best',
            'youtube_include_dash_manifest': False,
        })
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
        if 'entries' in info:
            if not info['entries']:
                logger.warning(f"yt-dlp вернул пустой список 'entries' для {url}")
                return None
            info = info['entries'][0]
            if not info:
                logger.warning(f"yt-dlp вернул None в 'entries' для {url}")
                return None
        base_filename_tmpl = ydl_opts['outtmpl']
        try:
            expected_base = ytdl.prepare_filename(info).rsplit('.', 1)[0]
        except Exception:
            extractor = info.get('extractor_key', 'unknown').lower()
            track_id = info.get('id', 'unknown_id')
            title = info.get('title', 'unknown_title')
            safe_title = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in title)[:100]
            expected_base = f"{DOWNLOADS_DIR}/{extractor}-{track_id}-{safe_title}"
        preferred_ext = '.' + ydl_opts['postprocessors'][0]['preferredcodec']
        filepath = expected_base + preferred_ext
        if not os.path.exists(filepath):
            logger.warning(f"Файл {filepath} не найден. Ищем с помощью glob: {expected_base}.*")
            found_files = glob.glob(f"{expected_base}.*")
            if found_files:
                audio_files = [f for f in found_files if f.lower().endswith(('.opus', '.mp3', '.ogg', '.m4a', '.aac', '.wav', '.flac'))]
                if audio_files:
                    filepath = audio_files[0]
                    logger.info(f"Найден аудио файл через glob: {filepath}")
                else:
                    filepath = found_files[0]
                    logger.warning(f"Не удалось найти аудио расширение, используем первое совпадение: {filepath}")
            else:
                logger.error(f"Не удалось найти скачанный файл по шаблону: {expected_base}.*")
                return None
        info['filepath'] = filepath
        return info
    except yt_dlp.utils.DownloadError as e:
        logger.warning(f"yt-dlp DownloadError при скачивании: {e}")
        raise
    except Exception as e:
        logger.error(f"Неожиданная ошибка при скачивании трека ({url}): {e}", exc_info=True)
        return None

async def search_youtube(query: str, max_results: int = 5) -> Optional[List[Dict[str, Any]]]:
    """Ищет видео на YouTube без скачивания."""
    logger.info(f"Поиск на YouTube: '{query}' (max_results={max_results})")
    ydl_opts = {
        'format': 'bestaudio',
        'extract_flat': True,
        'skip_download': True,
        'playlistend': max_results,
        'quiet': True,
        'no_warnings': True,
        'default_search': f'ytsearch{max_results}',
        'source_address': '0.0.0.0',
        'proxy': PROXY_URL,
        'socket_timeout': 5,
        'retries': 1,
        'geo_bypass': True,
        'geo_bypass_country': YDL_OPTS_BASE['geo_bypass_country'],
        'logtostderr': False,
        'ignoreerrors': True,
        'skip_download_archive': True,
        'youtube_include_dash_manifest': False,
    }
    try:
        ytdl = yt_dlp.YoutubeDL(ydl_opts)
        info = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ytdl.extract_info(query, download=False)
        )
        if not info or not info.get('entries'):
            logger.warning(f"Поиск на YouTube для '{query}' не вернул результатов.")
            return None
        valid_entries = []
        for entry in info['entries']:
            if not isinstance(entry, dict):
                continue
            # yt-dlp >=2023.03.04 для ytsearch с extract_flat=True не возвращает 'url', только 'id' и 'ie_key'
            if entry.get('url'):
                valid_entries.append(entry)
            elif entry.get('id') and entry.get('ie_key') == 'Youtube':
                entry['url'] = f"https://www.youtube.com/watch?v={entry['id']}"
                valid_entries.append(entry)
        logger.info(f"Найдено {len(valid_entries)} результатов для '{query}'")
        return valid_entries
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError при поиске '{query}': {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при поиске на YouTube для '{query}': {e}", exc_info=True)
        return None
