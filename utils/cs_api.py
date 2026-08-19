"""Модуль для взаимодействия с FACEIT Data API (статистика CS2).

REST-клиент с теми же гарантиями, что и :mod:`utils.dota_api`: переиспользуемая
сессия aiohttp, single-flight по cache_key (защита от cache-stampede), кэш в
таблице ``APICache`` и обёртка с ретраями (429 → Retry-After, 5xx → backoff,
4xx → не ретраим).
"""

import asyncio
import logging
from typing import Any, cast
from weakref import WeakValueDictionary

import aiohttp

from utils.dota_api import get_cached_response, save_to_cache

logger = logging.getLogger("bot.utils.cs_api")

BASE_URL = "https://open.faceit.com/data/v4"

_MAX_RETRY_AFTER_SECONDS = 60.0
_DEFAULT_RETRY_AFTER = 5.0

_session: aiohttp.ClientSession | None = None
_session_lock: asyncio.Lock | None = None
_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
_DEFAULT_CONNECTOR_LIMIT = 20

_inflight_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_inflight_locks_mutex: asyncio.Lock | None = None


class FaceitRateLimited(Exception):
    """FACEIT API вернул 429. Нужно подождать `retry_after` секунд."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"FACEIT rate limit, retry after {retry_after}s")
        self.retry_after = retry_after


class FaceitNonRetryable(Exception):
    """Невозвратная ошибка FACEIT API: 4xx (кроме 429 и 404)."""


class FaceitNotFound(Exception):
    """Ресурс не найден (404): игрок/матч не существует или нет CS2-данных."""


def _get_lock() -> asyncio.Lock:
    """Лениво создаёт Lock — на import time event loop может ещё не существовать."""
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


async def _get_session() -> aiohttp.ClientSession:
    """Возвращает переиспользуемую сессию aiohttp, создавая при необходимости."""
    global _session
    if _session is not None and not _session.closed:
        return _session

    async with _get_lock():
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(
                timeout=_DEFAULT_TIMEOUT,
                connector=aiohttp.TCPConnector(limit=_DEFAULT_CONNECTOR_LIMIT),
            )
    return _session


async def close_session() -> None:
    """Закрывает модульную сессию aiohttp."""
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


async def _get_inflight_lock(cache_key: str) -> asyncio.Lock:
    """Возвращает (или создаёт) Lock для single-flight по cache_key."""
    global _inflight_locks_mutex
    if _inflight_locks_mutex is None:
        _inflight_locks_mutex = asyncio.Lock()
    async with _inflight_locks_mutex:
        lock = _inflight_locks.get(cache_key)
        if lock is None:
            lock = asyncio.Lock()
            _inflight_locks[cache_key] = lock
        return lock


def _parse_retry_after(value: str | None) -> float:
    """Парсит заголовок Retry-After (секунды) с потолком и дефолтом."""
    if not value:
        return _DEFAULT_RETRY_AFTER
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_RETRY_AFTER
    return max(0.0, min(seconds, _MAX_RETRY_AFTER_SECONDS))


async def faceit_get(
    path: str,
    api_key: str,
    params: dict[str, Any] | None = None,
    cache_key: str | None = None,
    ttl: int = 300,
) -> dict[str, Any] | None:
    """Выполняет GET-запрос к FACEIT Data API.

    Возвращает данные при успехе или None для transient-ошибок (5xx, сеть,
    timeout). Для нон-retryable случаев бросает :class:`FaceitRateLimited` (429),
    :class:`FaceitNotFound` (404) или :class:`FaceitNonRetryable` (прочие 4xx).

    При наличии cache_key используется single-flight: одинаковые параллельные
    запросы ждут общий результат вместо повторного похода в API.
    """
    if cache_key is None:
        return await _do_faceit_get(path, api_key, params, cache_key=None, ttl=ttl)

    cached_data = await get_cached_response(cache_key)
    if cached_data is not None:
        return cached_data

    lock = await _get_inflight_lock(cache_key)
    async with lock:
        cached_data = await get_cached_response(cache_key)
        if cached_data is not None:
            return cached_data
        return await _do_faceit_get(path, api_key, params, cache_key=cache_key, ttl=ttl)


async def _do_faceit_get(
    path: str,
    api_key: str,
    params: dict[str, Any] | None,
    cache_key: str | None,
    ttl: int,
) -> dict[str, Any] | None:
    """Реальный HTTP-вызов к FACEIT без single-flight обвязки."""
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    try:
        session = await _get_session()
        async with session.get(
            url,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            status = response.status

            if status == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                logger.warning(
                    "FACEIT API rate limit (429): ждём %s сек перед повтором", retry_after
                )
                raise FaceitRateLimited(retry_after)

            if status == 404:
                raise FaceitNotFound(f"Ресурс не найден: {path}")

            if 400 <= status < 500:
                error_text = await response.text()
                logger.error("FACEIT API клиентская ошибка %s: %s", status, error_text[:200])
                raise FaceitNonRetryable(f"HTTP {status}")

            if status != 200:
                logger.error(f"HTTP ошибка FACEIT: {status}")
                return None

            data = await response.json()
            if not data:
                return None

            if cache_key:
                await save_to_cache(cache_key, data, ttl=ttl)

            return cast(dict[str, Any], data)

    except (FaceitRateLimited, FaceitNotFound, FaceitNonRetryable):
        raise
    except TimeoutError:
        logger.warning("Таймаут запроса к FACEIT API")
        return None
    except Exception as e:
        logger.error(f"Ошибка FACEIT API: {e}")
        return None


async def faceit_get_with_retry(
    path: str,
    api_key: str,
    params: dict[str, Any] | None = None,
    cache_key: str | None = None,
    ttl: int = 300,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    """Обёртка с повторными попытками вокруг :func:`faceit_get`.

    Поведение:
        - успех → возвращаем результат;
        - transient-ошибка (None) → экспоненциальный backoff;
        - 429 → ждём Retry-After, попытка не считается обычным retry;
        - 404 / прочие 4xx → сразу None (повторять бесполезно).
    """
    retry_delay: float = 1.0
    for attempt in range(max_retries):
        try:
            result = await faceit_get(path, api_key, params, cache_key, ttl)
        except FaceitRateLimited as exc:
            await asyncio.sleep(exc.retry_after)
            continue
        except (FaceitNotFound, FaceitNonRetryable):
            return None

        if result is not None:
            return result

        if attempt < max_retries - 1:
            logger.warning(
                "Попытка %s/%s не удалась. Ждём %sс...", attempt + 1, max_retries, retry_delay
            )
            await asyncio.sleep(retry_delay)
            retry_delay *= 2

    return None
