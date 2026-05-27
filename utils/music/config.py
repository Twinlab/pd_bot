"""Конфигурация музыкального модуля.

Содержит палитру цветов для эмбедов и общий логгер для всех файлов модуля.
Параметры подключения к Lavalink читаются напрямую из ``config.get_settings()``
в момент использования — это позволяет переопределять их в тестах без
перезагрузки модуля.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from config import get_settings

logger = logging.getLogger("bot.music")


class _ColorsProxy(Mapping[str, Any]):
    """Ленивый словарь цветов: ``get_settings()`` вызывается при первом обращении.

    Раньше ``COLORS`` инициализировался на import time и мешал тестам
    подменять settings до первого импорта ``utils.music.*``.
    """

    _KEYS = ("DEFAULT", "ERROR", "SUCCESS", "INFO", "WARNING")

    def __init__(self) -> None:
        self._cache: dict[str, Any] | None = None

    def _resolve(self) -> dict[str, Any]:
        if self._cache is None:
            settings = get_settings()
            self._cache = {
                "DEFAULT": settings.get_discord_color("default"),
                "ERROR": settings.get_discord_color("error"),
                "SUCCESS": settings.get_discord_color("success"),
                "INFO": settings.get_discord_color("info"),
                "WARNING": settings.get_discord_color("warning"),
            }
        return self._cache

    def __getitem__(self, key: str) -> Any:
        return self._resolve()[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._KEYS)

    def __len__(self) -> int:
        return len(self._KEYS)


COLORS: Mapping[str, Any] = _ColorsProxy()
