"""Музыкальный модуль на базе Lavalink v4 и wavelink 3.x.

* :class:`MusicPlayer` — расширение ``wavelink.Player`` для нашего single-guild
  контекста (вспомогательные поля и проверка прав).
* :func:`setup_node` / :func:`close_nodes` — управление подключением к Lavalink.
* Карточки Components V2 и View лежат рядом и используются ``cogs/music.py``.
"""

from .config import logger
from .embeds import (
    added_playlist_card,
    added_to_queue_card,
    format_duration,
    status_card,
)
from .player import MusicPlayer, close_nodes, setup_node
from .ui import (
    NowPlayingView,
    QueueLayoutView,
    SearchLayoutView,
    now_playing_static_view,
)

__all__ = [
    "MusicPlayer",
    "NowPlayingView",
    "QueueLayoutView",
    "SearchLayoutView",
    "added_playlist_card",
    "added_to_queue_card",
    "close_nodes",
    "format_duration",
    "logger",
    "now_playing_static_view",
    "setup_node",
    "status_card",
]
