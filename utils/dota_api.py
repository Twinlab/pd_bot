"""Модуль для взаимодействия с API Stratz для получения данных о матчах Dota 2.

Использует Tortoise ORM для кэширования и Pydantic для валидации.
"""

import asyncio
import logging
import time
from typing import Any, cast
from weakref import WeakValueDictionary

import aiohttp

from utils.models import APICache

logger = logging.getLogger("bot.utils.dota_api")

CACHE_TTL = 300  # 5 минут

# Лимиты ретраев. На 429 ждём Retry-After (но не больше потолка),
# на 5xx — обычный экспоненциальный backoff.
_MAX_RETRY_AFTER_SECONDS = 60.0
_DEFAULT_RETRY_AFTER = 5.0

_session: aiohttp.ClientSession | None = None
# Защищает _get_session от гонки двух корутин.
_session_lock: asyncio.Lock | None = None
_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
_DEFAULT_CONNECTOR_LIMIT = 20

# Single-flight локи на cache_key: дубли одинаковых запросов ждут общий результат.
_inflight_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_inflight_locks_mutex: asyncio.Lock | None = None


class StratzRateLimited(Exception):
    """Stratz API вернул 429. Нужно подождать `retry_after` секунд."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Stratz rate limit, retry after {retry_after}s")
        self.retry_after = retry_after


class StratzNonRetryable(Exception):
    """Невозвратная ошибка Stratz API: 4xx (кроме 429), GraphQL-ошибки и т.п."""


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
        # Double-checked locking: между первым check и взятием лока кто-то мог уже создать.
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


async def prune_expired_cache() -> int:
    """Удаляет протухшие записи из APICache. Возвращает количество удалённых."""
    try:
        now = time.time()
        all_entries = await APICache.all().only("key", "timestamp", "ttl")
        expired_keys = [e.key for e in all_entries if e.timestamp + e.ttl <= now]
        if not expired_keys:
            return 0
        deleted = await APICache.filter(key__in=expired_keys).delete()
        logger.info(f"prune_expired_cache: удалено {deleted} протухших записей.")
        return deleted
    except Exception as e:
        logger.error(f"Ошибка prune_expired_cache: {e}", exc_info=True)
        return 0


async def get_cached_response(key: str) -> dict[str, Any] | None:
    """Получает данные из кэша БД, если они актуальны."""
    try:
        cache_entry = await APICache.get_or_none(key=key)
        if cache_entry:
            current_time = time.time()
            if cache_entry.timestamp + cache_entry.ttl > current_time:
                logger.debug(f"Кэш найден для {key}")
                return cast(dict[str, Any], cache_entry.data)
            else:
                # Кэш протух, удаляем
                await cache_entry.delete()
    except Exception as e:
        logger.error(f"Ошибка при чтении кэша: {e}")
    return None


async def save_to_cache(key: str, data: dict[str, Any], ttl: int = CACHE_TTL) -> None:
    """Сохраняет данные в кэш БД."""
    try:
        await APICache.update_or_create(
            key=key,
            defaults={
                "data": data,
                "timestamp": time.time(),
                "ttl": ttl,
            },
        )
        logger.debug(f"Сохранено в кэш: {key}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении кэша: {e}")


def _parse_retry_after(value: str | None) -> float:
    """Парсит заголовок Retry-After (секунды) с потолком и дефолтом.

    Stratz обычно отдаёт целое число секунд. HTTP-Date формат не поддерживаем —
    в этом случае возвращаем дефолт.
    """
    if not value:
        return _DEFAULT_RETRY_AFTER
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_RETRY_AFTER
    return max(0.0, min(seconds, _MAX_RETRY_AFTER_SECONDS))


async def query_api(
    query: str,
    url: str,
    headers: dict[str, str],
    variables: dict[str, Any] | None = None,
    cache_key: str | None = None,
) -> dict[str, Any] | None:
    """Выполняет GraphQL-запрос к API Stratz.

    Возвращает данные при успехе или None для transient-ошибок (5xx, сеть,
    timeout) — их имеет смысл ретраить. Для нон-retryable случаев бросает
    `StratzRateLimited` (429) или `StratzNonRetryable` (4xx, GraphQL errors).

    При наличии cache_key используем single-flight: если такой же запрос уже
    выполняется параллельно, ждём его результат вместо повторного похода в API.
    """
    if cache_key is None:
        return await _do_query_api(query, url, headers, variables, cache_key=None)

    cached_data = await get_cached_response(cache_key)
    if cached_data is not None:
        return cached_data

    # Защита от cache-stampede: пока один запрос летит к API, остальные ждут.
    lock = await _get_inflight_lock(cache_key)
    async with lock:
        # Повторный check — пока ждали лок, кто-то мог уже наполнить кэш.
        cached_data = await get_cached_response(cache_key)
        if cached_data is not None:
            return cached_data
        return await _do_query_api(query, url, headers, variables, cache_key=cache_key)


async def _do_query_api(
    query: str,
    url: str,
    headers: dict[str, str],
    variables: dict[str, Any] | None,
    cache_key: str | None,
) -> dict[str, Any] | None:
    """Реальный HTTP-вызов к Stratz без single-flight обвязки."""
    request_headers = headers.copy()
    request_headers["User-Agent"] = "STRATZ_API"

    try:
        session = await _get_session()
        async with session.post(
            url,
            json={"query": query, "variables": variables},
            headers=request_headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            status = response.status

            # 429: получили rate limit — отдаём Retry-After через исключение,
            # чтобы retry-обёртка могла подождать ровно столько, сколько нужно,
            # вместо слепого backoff.
            if status == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                logger.warning(
                    "Stratz API rate limit (429): ждём %s сек перед повтором",
                    retry_after,
                )
                raise StratzRateLimited(retry_after)

            # 4xx (кроме 429): запрос некорректен или не авторизован —
            # ретрай не поможет.
            if 400 <= status < 500:
                error_text = await response.text()
                logger.error("Stratz API клиентская ошибка %s: %s", status, error_text[:200])
                raise StratzNonRetryable(f"HTTP {status}")

            # 5xx и прочее: transient, имеет смысл ретраить.
            if status != 200:
                logger.error(f"HTTP ошибка: {status}")
                return None

            json_data = await response.json()

            if "errors" in json_data:
                # GraphQL-ошибки: формат запроса/прав, ретрай не поможет.
                logger.error(f"Ошибки GraphQL: {json_data['errors']}")
                raise StratzNonRetryable("GraphQL errors")

            data = json_data.get("data")
            if not data:
                return None

            # 3. Сохранение в кэш
            if cache_key:
                await save_to_cache(cache_key, data)

            return cast(dict[str, Any], data)

    except (StratzRateLimited, StratzNonRetryable):
        # Пробрасываем в retry-обёртку — она решит, что делать.
        raise
    except TimeoutError:
        logger.warning("Таймаут запроса к Stratz API")
        return None
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        return None


async def query_api_with_retry(
    query: str,
    url: str,
    headers: dict[str, str],
    variables: dict[str, Any] | None = None,
    cache_key: str | None = None,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    """Обёртка с повторными попытками.

    Поведение:
        - успех → возвращаем результат;
        - transient-ошибка (None из `query_api`) → экспоненциальный backoff;
        - 429 (`StratzRateLimited`) → ждём Retry-After, попытка не считается
          обычным retry;
        - non-retryable (`StratzNonRetryable`) → сразу возвращаем None,
          чтобы не долбить API с заведомо неправильным запросом.
    """
    retry_delay: float = 1.0
    for attempt in range(max_retries):
        try:
            result = await query_api(query, url, headers, variables, cache_key)
        except StratzRateLimited as exc:
            await asyncio.sleep(exc.retry_after)
            # Не увеличиваем счётчик попыток — мы просто ждали лимит.
            continue
        except StratzNonRetryable:
            # 4xx или GraphQL-ошибка — повторять бесполезно.
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


async def fetch_items_data(url: str, headers: dict[str, str]) -> dict[int, dict[str, str]]:
    """Получает информацию о предметах."""
    cache_key = "dota_items"
    # Увеличенный TTL для предметов (50 минут)
    cached_data = await get_cached_response(cache_key)

    # Если данные есть в кэше, нам нужно их преобразовать обратно в нужный формат,
    # так как мы сохраняем "сырой" ответ API или уже обработанный?
    # В старой версии мы сохраняли обработанный словарь.
    # Давайте сохранять обработанный словарь для удобства.

    if cached_data is not None:
        # В save_to_cache мы сохраняем то, что передаем.
        # Если мы сохраним items_dict, то получим его обратно.
        # Но get_cached_response возвращает dict[str, Any].
        # Нам нужно привести ключи к int.
        return {int(k): v for k, v in cached_data.items()}

    query = """
    {
      constants {
        items {
          id
          name
          displayName
          image
        }
      }
    }
    """

    # Здесь мы используем query_api, который возвращает 'data' из ответа GraphQL.
    # Но для предметов мы хотим закэшировать уже обработанный словарь, чтобы не парсить каждый раз.
    # Поэтому мы вызовем query_api БЕЗ cache_key, обработаем, и сохраним сами.

    data = await query_api(query, url, headers)
    if not data:
        return {}

    # Валидация через Pydantic
    try:
        # data = {'constants': {'items': [...]}}
        # Наша модель StratzResponse ожидает {'data': ...}, но query_api возвращает содержимое 'data'.
        # Значит нам нужно валидировать содержимое.
        # ConstantsResponse ожидает {'constants': ...}

        # Импортируем здесь, чтобы избежать циклических импортов если что
        from utils.schemas import ConstantsResponse

        response_model = ConstantsResponse.model_validate(data)

        items_dict = {}
        for item in response_model.constants.items:
            items_dict[item.id] = {
                "name": item.name,
                "displayName": item.displayName or "",
                "image": item.image or "",
            }

        # Сохраняем в кэш с долгим TTL (50 минут = 3000 сек)
        await save_to_cache(cache_key, items_dict, ttl=3000)

        return items_dict

    except Exception as e:
        logger.error(f"Ошибка валидации данных предметов: {e}")
        return {}
