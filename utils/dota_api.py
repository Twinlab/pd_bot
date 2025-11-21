"""Модуль для взаимодействия с API Stratz для получения данных о матчах Dota 2.

Использует Tortoise ORM для кэширования и Pydantic для валидации.
"""

import asyncio
import logging
import time
from typing import Any

import aiohttp

from utils.models import APICache

logger = logging.getLogger("bot.utils.dota_api")

CACHE_TTL = 300  # 5 минут


async def get_cached_response(key: str) -> dict[str, Any] | None:
    """Получает данные из кэша БД, если они актуальны."""
    try:
        cache_entry = await APICache.get_or_none(key=key)
        if cache_entry:
            current_time = time.time()
            if cache_entry.timestamp + cache_entry.ttl > current_time:
                logger.debug(f"Кэш найден для {key}")
                return cache_entry.data
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


async def query_api(
    query: str,
    url: str,
    headers: dict[str, str],
    variables: dict[str, Any] | None = None,
    cache_key: str | None = None,
) -> dict[str, Any] | None:
    """Выполняет GraphQL-запрос к API Stratz."""
    # 1. Проверка кэша
    if cache_key:
        cached_data = await get_cached_response(cache_key)
        if cached_data:
            return cached_data

    # 2. Запрос к API
    request_headers = headers.copy()
    request_headers["User-Agent"] = "STRATZ_API"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"query": query, "variables": variables},
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    logger.error(f"HTTP ошибка: {response.status}")
                    return None

                json_data = await response.json()

                if "errors" in json_data:
                    logger.error(f"Ошибки GraphQL: {json_data['errors']}")
                    return None

                data = json_data.get("data")
                if not data:
                    return None

                # 3. Сохранение в кэш
                if cache_key:
                    await save_to_cache(cache_key, data)

                return data

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
    """Обертка с повторными попытками."""
    retry_delay = 1
    for attempt in range(max_retries):
        result = await query_api(query, url, headers, variables, cache_key)
        if result is not None:
            return result

        logger.warning(f"Попытка {attempt + 1}/{max_retries} не удалась. Ждем {retry_delay}с...")
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

    if cached_data:
        # В save_to_cache мы сохраняем то, что передаем.
        # Если мы сохраним items_dict, то получим его обратно.
        # Но get_cached_response возвращает Dict[str, Any].
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
