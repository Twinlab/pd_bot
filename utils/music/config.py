"""Конфигурационный файл для музыкального модуля.

Содержит настройки логгера, пути, цвета для эмбедов,
опции для yt-dlp и FFmpeg, а также загрузку URL прокси-сервера.
"""

import logging
from pathlib import Path

from config import get_settings

# --- Логгер для конфигурационного модуля музыки ---
logger = logging.getLogger("bot.utils.music.config")

settings = get_settings()

# --- Константы и конфигурация ---
DOWNLOADS_DIR = Path(
    getattr(settings, "music", {}).get("downloads_dir", "downloads")
    if hasattr(settings, "music")
    else "downloads"
)
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Цвета для Embeds
COLORS = {
    "DEFAULT": settings.get_discord_color("default"),
    "ERROR": settings.get_discord_color("error"),
    "SUCCESS": settings.get_discord_color("success"),
    "INFO": settings.get_discord_color("info"),
    "WARNING": settings.get_discord_color("warning"),
}

# Загрузка PROXY_URL из новой системы настроек
PROXY_URL = settings.proxy_url

# Опции для yt-dlp
YDL_OPTS_BASE = {
    "format": "bestaudio/best",
    "outtmpl": str(DOWNLOADS_DIR / "%(extractor)s-%(id)s-%(title)s.%(ext)s"),
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "proxy": PROXY_URL,
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }
    ],
}

# Опции FFmpeg
FFMPEG_OPTIONS = {
    "before_options": "",
    "options": (
        getattr(settings, "music", {}).get("ffmpeg_options", "-vn -loglevel info -hide_banner")
        if hasattr(settings, "music")
        else "-vn -loglevel info -hide_banner"
    ),
}
