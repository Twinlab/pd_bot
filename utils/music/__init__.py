"""Пакет утилит для музыкального кога, включая плеер, интерфейс и интеграцию с YouTube."""

from .config import COLORS
from .embeds import create_embed
from .player import MusicPlayer
from .ui import SearchView
from .yt_integration import search_youtube

__all__ = [
    "COLORS",
    "MusicPlayer",
    "SearchView",
    "create_embed",
    "search_youtube",
]
