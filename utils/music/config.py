"""Конфигурационный файл для музыкального модуля.

Содержит настройки логгера, пути, цвета для эмбедов,
опции для yt-dlp и FFmpeg, а также загрузку URL прокси-сервера.
"""

import logging
from pathlib import Path

import discord

# --- Логгер для конфигурационного модуля музыки ---
logger = logging.getLogger("bot.utils.music.config")

# --- Константы и конфигурация ---
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Цвета для Embeds
COLORS = {
    "DEFAULT": discord.Color.blue(),
    "ERROR": discord.Color.red(),
    "SUCCESS": discord.Color.green(),
    "INFO": discord.Color.gold(),
    "WARNING": discord.Color.orange(),
}

# Загрузка PROXY_URL из основного конфига
try:
    from config import load_config as load_main_config

    _config = load_main_config()
    PROXY_URL = _config.get("PROXY_URL", None)
except ImportError:
    logger.warning("Не удалось импортировать основной конфиг. PROXY_URL не будет использоваться.")
    PROXY_URL = None
except Exception as e:
    logger.error(f"Ошибка загрузки основного конфига: {e}", exc_info=True)
    PROXY_URL = None

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
    "options": "-vn -loglevel info -hide_banner",
}
