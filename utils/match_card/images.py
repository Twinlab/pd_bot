"""Безопасная загрузка картинок (аватар/арт героя/иконки предметов/сплеши карт).

Картинки повторяются между вызовами (один герой, одни и те же предметы), поэтому
держим in-memory кэш по URL. Любая ошибка сети/HTTP → None: карточка обязана
рисоваться даже без внешних изображений (рендер подставит фолбэк).
"""

import asyncio
import logging
from pathlib import Path

import aiohttp

logger = logging.getLogger("bot.utils.match_card.images")

_MAPS_DIR = Path(__file__).resolve().parent / "assets" / "maps"

_session: aiohttp.ClientSession | None = None
_session_lock: asyncio.Lock | None = None
_cache: dict[str, bytes | None] = {}
_MAX_BYTES = 8 * 1024 * 1024


def _lock() -> asyncio.Lock:
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _lock():
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15, connect=5))
    return _session


async def close_session() -> None:
    """Закрывает шаренную aiohttp-сессию (при выгрузке кога)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


async def fetch_image_bytes(url: str | None) -> bytes | None:
    """Скачивает байты картинки по URL с in-memory кэшем; None при любой ошибке.

    Args:
        url: Полный URL картинки (или None/пустая строка → сразу None).

    Returns:
        Сырые байты изображения или None, если URL пуст или загрузка не удалась.
    """
    if not url:
        return None
    if url in _cache:
        return _cache[url]

    result: bytes | None = None
    try:
        session = await _get_session()
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                if data and len(data) <= _MAX_BYTES:
                    result = data
            else:
                logger.debug("Картинка %s вернула HTTP %s", url, resp.status)
    except Exception as e:
        logger.debug("Не удалось загрузить картинку %s: %s", url, e)

    _cache[url] = result
    return result


def load_map_image(map_name: str) -> bytes | None:
    """Читает забандленный сплеш карты CS (``assets/maps/<map>.jpg``); None, если нет файла.

    Args:
        map_name: Имя карты без префикса ``de_`` (например ``dust2``).

    Returns:
        Байты картинки или None — тогда рендер нарисует procedural-фолбэк.
    """
    for ext in ("jpg", "jpeg", "png", "webp"):
        path = _MAPS_DIR / f"{map_name}.{ext}"
        if path.exists():
            try:
                return path.read_bytes()
            except OSError as e:
                logger.debug("Не удалось прочитать сплеш карты %s: %s", path, e)
                return None
    return None


def item_image_url(item_name: str) -> str:
    """Строит URL иконки предмета Dota из его ``name`` (``item_blink`` → Valve cdn).

    Args:
        item_name: Внутреннее имя предмета вида ``item_blink``.

    Returns:
        URL PNG-иконки на Valve cdn.
    """
    short = item_name.removeprefix("item_")
    return f"https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/{short}.png"
