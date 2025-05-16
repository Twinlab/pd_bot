"""Модуль для взаимодействия с API Stratz для получения данных о матчах Dota 2.

Этот модуль предоставляет функции для выполнения GraphQL-запросов к API Stratz,
кэширования результатов в памяти и на диске, а также получения информации о предметах.
Включает механизмы повторных попыток при ошибках и управление кэшем.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional, cast

import aiohttp

logger = logging.getLogger("bot.utils.dota_api")

# Глобальные переменные для кэширования в памяти
match_cache: dict[str, dict[str, Any]] = (
    {}
)  # {cache_key: {'data': dict[str, Any], 'timestamp': float}}
items_cache: dict[str, Any] = {}  # {'data': dict[int, dict[str, str]], 'timestamp': float}
CACHE_TTL = 300  # Время жизни кэша матчей в секундах (5 минут)
CACHE_DIR = "data/cache"  # Директория для хранения кэша на диске

# Создаем директорию для кэша, если её не существует
os.makedirs(CACHE_DIR, exist_ok=True)

# --- Вспомогательные функции для работы с файлами ---


async def read_json_file(file_path: str) -> dict[str, Any]:
    """Асинхронно читает JSON-файл и возвращает его содержимое как словарь.

    Args:
        file_path: Путь к JSON-файлу.

    Returns:
        Словарь с данными из JSON-файла или пустой словарь в случае ошибки.
    """
    try:
        # Используем encoding='utf-8' для совместимости
        with open(file_path, "r", encoding="utf-8") as f:
            # Мы ожидаем, что JSON верхнего уровня всегда будет словарем
            loaded_data = json.load(f)
            if not isinstance(loaded_data, dict):
                logger.error(f"Ожидался словарь в JSON, получен {type(loaded_data)}: {file_path}")
                return {}
            return cast(dict[str, Any], loaded_data)
    except FileNotFoundError:
        logger.warning(f"Файл не найден: {file_path}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в файле: {file_path}")
        return {}
    except Exception as e:
        logger.error(f"Неизвестная ошибка при чтении файла {file_path}: {e}")
        return {}


async def write_json_file(file_path: str, data: dict) -> bool:
    """Асинхронно записывает словарь в JSON-файл.

    Args:
        file_path: Путь к файлу для записи.
        data: Словарь с данными для записи.

    Returns:
        True в случае успешной записи, False в случае ошибки.
    """
    try:
        # Используем encoding='utf-8' и безопасное сохранение через временный файл
        temp_file_path = f"{file_path}.tmp"  # Определяем временный путь
        with open(temp_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)  # Добавляем отступы для читаемости
        os.replace(temp_file_path, file_path)  # Атомарная замена
        return True
    except Exception as e:
        logger.error(f"Ошибка при записи в файл {file_path}: {e}")
        return False


# --- Функции управления кэшем ---


async def load_cache_from_disk() -> None:
    """Загружает кэш матчей и предметов из файлов на диске в память при запуске.

    Читает файлы match_cache.json и items_cache.json из директории кэша
    и загружает их содержимое в глобальные переменные match_cache и items_cache.
    """
    global match_cache, items_cache

    try:
        match_cache_file = os.path.join(CACHE_DIR, "match_cache.json")
        items_cache_file = os.path.join(CACHE_DIR, "items_cache.json")

        if os.path.exists(match_cache_file):
            match_cache = await read_json_file(match_cache_file)

        if os.path.exists(items_cache_file):
            items_cache = await read_json_file(items_cache_file)

        logger.info(
            "Кэш загружен с диска: "
            + f"{len(match_cache)} матчей, "
            + f"{len(items_cache.get('data', {}))} предметов."
        )
    except Exception as e:
        logger.error(f"Ошибка при загрузке кэша с диска: {e}")


async def save_cache_to_disk() -> bool:
    """Сохраняет текущий кэш матчей и предметов из памяти в файлы на диске.

    Returns:
        True в случае успешного сохранения, False в случае ошибки.
    """
    try:
        match_cache_file = os.path.join(CACHE_DIR, "match_cache.json")
        items_cache_file = os.path.join(CACHE_DIR, "items_cache.json")

        await write_json_file(match_cache_file, match_cache)
        await write_json_file(items_cache_file, items_cache)

        logger.debug("Кэш сохранен на диск.")  # Изменено на debug, т.к. вызывается часто
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении кэша: {e}")
        return False


# --- Функции взаимодействия с API Stratz ---


async def query_api(
    query: str,
    url: str,
    headers: dict,
    variables: Optional[dict] = None,
    cache_key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Выполняет GraphQL-запрос к API Stratz.

    Проверяет кэш матчей перед выполнением запроса.
    Сохраняет успешные результаты в кэш (в памяти и на диск).

    Args:
        query: Текст GraphQL-запроса.
        url: URL API Stratz.
        headers: Заголовки запроса (включая токен авторизации).
        variables: Переменные для GraphQL-запроса (опционально).
        cache_key: Ключ для кэширования этого запроса (опционально).

    Returns:
        Словарь с данными ('data') из ответа API или None в случае ошибки/отсутствия данных.
    """
    # Проверка кэша
    if cache_key:
        current_time = time.time()
        # Проверяем наличие ключа в кэше и не истекло ли время жизни (TTL)
        if (
            cache_key in match_cache
            and match_cache[cache_key]["timestamp"] + CACHE_TTL > current_time
        ):
            logger.debug(f"Кэш найден для {cache_key}")
            return cast(dict[str, Any], match_cache[cache_key]["data"])

    # 2. Выполнение запроса к API
    # Копируем заголовки и добавляем обязательный User-Agent для Stratz API
    request_headers = headers.copy()
    request_headers["User-Agent"] = "STRATZ_API"

    try:
        # Используем aiohttp для асинхронного POST-запроса
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"query": query, "variables": variables},
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=10),  # Таймаут запроса 10 секунд
            ) as response:
                logger.info(
                    f"Запрос к Stratz API: {url}, Статус: {response.status}, Ключ кэша: {cache_key}"
                )

                # Проверяем HTTP статус ответа
                if response.status != 200:
                    logger.error(f"HTTP ошибка: {response.status}")
                    return None

                # Читаем и декодируем JSON из ответа
                json_data = await response.json()

                # Проверяем наличие поля 'errors' в ответе GraphQL
                if "errors" in json_data:
                    logger.error(f"Ошибки GraphQL: {json_data['errors']}")
                    return None

                # 3. Кэширование результата (если есть ключ и данные)
                if cache_key and "data" in json_data:
                    match_cache[cache_key] = {
                        "data": json_data["data"],
                        "timestamp": time.time(),  # Записываем время получения данных
                    }
                    logger.debug(f"Сохранено в кэш: {cache_key}")
                    # Запускаем асинхронную задачу для сохранения кэша на диск
                    # (не блокирует основной поток)
                    asyncio.create_task(save_cache_to_disk())

                # Возвращаем только часть 'data' из ответа
                # Мы ожидаем, что поле 'data' будет словарем, если оно есть
                data_field = json_data.get("data")
                if data_field is not None and not isinstance(data_field, dict):
                    logger.error(
                        f"Поле 'data' в ответе API не является словарем: {type(data_field)}"
                    )
                    return None
                return cast(Optional[dict[str, Any]], data_field)
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        return None


async def query_api_with_retry(
    query: str,
    url: str,
    headers: dict,
    variables: Optional[dict] = None,
    cache_key: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[dict[str, Any]]:
    """Обертка для `query_api`, добавляющая логику повторных попыток при ошибках (None в ответе).

    Использует экспоненциальную задержку между попытками.

    Args:
        query: Текст GraphQL-запроса.
        url: URL API Stratz.
        headers: Заголовки запроса (включая токен авторизации).
        variables: Переменные для GraphQL-запроса (опционально).
        cache_key: Ключ для кэширования этого запроса (опционально).
        max_retries: Максимальное количество повторных попыток.

    Returns:
        Результат `query_api` или None, если все попытки не удались.
    """
    retry_delay = 1  # Начальная задержка в секундах

    for attempt in range(max_retries):
        result = await query_api(query, url, headers, variables, cache_key)
        if result is not None:
            return result  # Возвращаем успешный результат

        # Если query_api вернула None (ошибка), ждем и повторяем
        logger.warning(
            (
                f"Попытка запроса {attempt + 1}/{max_retries} не удалась (cache_key: {cache_key}). "
                f"Повтор через {retry_delay} сек..."
            )
        )
        await asyncio.sleep(retry_delay)
        retry_delay *= 2  # Удваиваем задержку для следующей попытки

    logger.error(f"Все {max_retries} попыток запроса не удались (cache_key: {cache_key}).")
    return None


async def fetch_items_data(url: str, headers: dict) -> dict[int, dict[str, str]]:
    """Получает и кэширует информацию о предметах Dota 2 из API Stratz.

    Использует кэш в памяти (`items_cache`) с увеличенным TTL.

    Args:
        url: URL API Stratz.
        headers: Заголовки запроса (с токеном).

    Returns:
        Словарь {item_id: {'name': ..., 'displayName': ..., 'image': ...}} или пустой словарь.
    """
    global items_cache

    # Если данные уже в кэше и не устарели, используем их
    current_time = time.time()
    # Умножаем стандартный TTL на 10 (50 минут) для кэша предметов
    if (
        "data" in items_cache
        and "timestamp" in items_cache
        and items_cache["timestamp"] + CACHE_TTL * 10 > current_time
    ):
        logger.debug("Используется кэш предметов.")
        return cast(dict[int, dict[str, str]], items_cache["data"])

    # Если кэша нет или он устарел, выполняем запрос к API
    logger.info("Запрос данных о предметах из API Stratz...")
    items_query = """
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

    items_data = await query_api(items_query, url, headers)

    # Обрабатываем успешный ответ
    if items_data and "constants" in items_data and "items" in items_data["constants"]:
        # Преобразуем список предметов в словарь {item_id: {details}}
        items_dict = {}
        for item in items_data["constants"]["items"]:
            item_id = item.get("id")
            if item_id is not None:
                items_dict[item_id] = {
                    "name": item.get("name", ""),
                    "displayName": item.get("displayName", ""),
                    "image": item.get("image", ""),  # URL изображения предмета
                }

        # Сохраняем отформатированный словарь в глобальный кэш предметов
        items_cache = {
            "data": items_dict,
            "timestamp": time.time(),  # Записываем время обновления кэша
        }

        # Асинхронно сохраняем обновленный кэш на диск
        asyncio.create_task(save_cache_to_disk())

        logger.info(f"Данные о {len(items_dict)} предметах получены и кэшированы.")
        return items_dict

    logger.warning("Не удалось получить данные о предметах")
    return {}


# --- Инициализация кэша при запуске ---


async def init() -> None:
    """Асинхронная функция для загрузки кэша с диска при старте.

    Вызывает load_cache_from_disk() для инициализации кэша при запуске приложения.
    """
    await load_cache_from_disk()
