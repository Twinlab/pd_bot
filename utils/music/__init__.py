"""Музыкальный модуль на базе Lavalink v4 и wavelink 3.x.

* :class:`MusicPlayer` — расширение ``wavelink.Player`` для нашего single-guild
  контекста (вспомогательные поля и проверка прав).
* :func:`setup_node` / :func:`close_nodes` — управление подключением к Lavalink.
* Эмбеды и View лежат рядом и используются ``cogs/music.py``.
"""

from .config import COLORS, logger
from .embeds import (
    added_playlist_card,
    added_playlist_embed,
    added_to_queue_card,
    added_to_queue_embed,
    create_embed,
    format_duration,
    now_playing_embed,
    queue_embed,
    status_card,
)
from .player import MusicPlayer, close_nodes, setup_node
from .ui import (
    NowPlayingView,
    PlayerControlView,
    QueueLayoutView,
    QueueView,
    SearchLayoutView,
    SearchView,
    now_playing_static_view,
)

__all__ = [
    "COLORS",
    "MusicPlayer",
    "NowPlayingView",
    "PlayerControlView",
    "QueueLayoutView",
    "QueueView",
    "SearchLayoutView",
    "SearchView",
    "added_playlist_card",
    "added_playlist_embed",
    "added_to_queue_card",
    "added_to_queue_embed",
    "close_nodes",
    "create_embed",
    "format_duration",
    "logger",
    "now_playing_static_view",
    "now_playing_embed",
    "queue_embed",
    "setup_node",
    "status_card",
]
