# dota_api.py
import json
import requests
import time
import logging
 
logger = logging.getLogger("dota_bot")
 
# Кэш для хранения данных
match_cache = {}
items_cache = {}
CACHE_TTL = 300  # 5 минут в секундах
 
# Функция для чтения JSON-данных из файла
def read_json_file(file_name):
    try:
        with open(file_name) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при чтении файла {file_name}: {e}")
        return {}
 
# Функция для выполнения GraphQL-запроса к API с кэшированием
def query_api(query, url, headers, variables=None, cache_key=None):
    # Проверка кэша
    if cache_key:
        current_time = time.time()
        if cache_key in match_cache and match_cache[cache_key]['timestamp'] + CACHE_TTL > current_time:
            logger.info(f"Использую кэшированные данные для {cache_key}")
            return match_cache[cache_key]['data']
    
    # Добавляем требуемый заголовок User-Agent
    request_headers = headers.copy()
    request_headers['User-Agent'] = 'STRATZ_API'
    
    try:
        # Выполняем запрос
        response = requests.post(url, json={'query': query, 'variables': variables}, headers=request_headers, timeout=10)
        
        # Логируем информацию
        logger.info(f"API запрос: {url}, Код статуса: {response.status_code}")
        
        # Проверяем код состояния
        response.raise_for_status()
        
        # Пытаемся разобрать JSON
        json_data = response.json()
        
        # Проверяем на наличие ошибок GraphQL
        if 'errors' in json_data:
            logger.error(f"Ошибки GraphQL: {json_data['errors']}")
            return None
            
        # Сохраняем в кэш, если запрос успешен
        if cache_key and 'data' in json_data:
            match_cache[cache_key] = {
                'data': json_data['data'],
                'timestamp': time.time()
            }
            
        return json_data.get('data')
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        return None
 
# Функция для повторного запроса при ошибке
def query_api_with_retry(query, url, headers, variables=None, cache_key=None, max_retries=3):
    retry_delay = 1  # Начальная задержка в секундах
    
    for attempt in range(max_retries):
        result = query_api(query, url, headers, variables, cache_key)
        if result is not None:
            return result
            
        # Если результат None, делаем паузу и пробуем снова
        logger.info(f"Попытка {attempt+1} не удалась, повторяю через {retry_delay} сек...")
        time.sleep(retry_delay)
        retry_delay *= 2  # Увеличиваем задержку экспоненциально
    
    logger.warning("Все попытки исчерпаны")
    return None
 
# Функция для получения информации о предметах
def fetch_items_data(url, headers):
    global items_cache
    
    # Если данные уже в кэше и не устарели, используем их
    current_time = time.time()
    if 'data' in items_cache and 'timestamp' in items_cache and items_cache['timestamp'] + CACHE_TTL * 10 > current_time:
        logger.info("Использую кэшированные данные о предметах")
        return items_cache['data']
    
    # Запрашиваем данные о предметах из API
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
    
    items_data = query_api(items_query, url, headers)
    
    if items_data and 'constants' in items_data and 'items' in items_data['constants']:
        # Создаем словарь {id: {name, displayName, image}} для удобного доступа
        items_dict = {}
        for item in items_data['constants']['items']:
            item_id = item.get('id')
            if item_id is not None:
                items_dict[item_id] = {
                    'name': item.get('name', ''),
                    'displayName': item.get('displayName', ''),
                    'image': item.get('image', '')
                }
        
        # Сохраняем в кэш
        items_cache = {
            'data': items_dict,
            'timestamp': time.time()
        }
        
        logger.info(f"Получены данные о {len(items_dict)} предметах")
        return items_dict
    
    logger.warning("Не удалось получить данные о предметах")
    return {}