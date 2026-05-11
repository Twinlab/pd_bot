"""Музыкальный модуль на базе Lavalink v4 и wavelink 3.x.

* :class:`MusicPlayer` — расширение ``wavelink.Player`` для нашего single-guild
  контекста (вспомогательные поля и проверка прав).
* :func:`setup_node` / :func:`close_nodes` — управление подключением к Lavalink.
* Эмбеды и View лежат рядом и используются ``cogs/music.py``.
"""

from .config import COLORS, logger
from .embeds import (
    added_playlist_embed,
    added_to_queue_embed,
    create_embed,
    format_duration,
    now_playing_embed,
    queue_embed,
)
from .player import MusicPlayer, close_nodes, setup_node
from .ui import PlayerControlView, QueueView, SearchView

__all__ = [
    "COLORS",
    "MusicPlayer",
    "PlayerControlView",
    "QueueView",
    "SearchView",
    "added_playlist_embed",
    "added_to_queue_embed",
    "close_nodes",
    "create_embed",
    "format_duration",
    "logger",
    "now_playing_embed",
    "queue_embed",
    "setup_node",
]
