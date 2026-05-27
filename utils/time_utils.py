"""Общие тайм-зонные константы и вспомогалки.

Один источник истины для всего проекта, чтобы каждый ког не объявлял
``ZoneInfo("Europe/Moscow")`` у себя.
"""

from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
