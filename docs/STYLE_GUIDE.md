# Руководство по стилю кода PD Bot

Это руководство содержит подробные правила и рекомендации по стилю кода для проекта PD Bot. Соблюдение этих правил обеспечивает единообразие кода и упрощает его поддержку.

## Содержание

1. [Форматирование кода](#1-форматирование-кода)
2. [Именование](#2-именование)
3. [Импорты](#3-импорты)
4. [Типизация](#4-типизация)
5. [Документация](#5-документация)
6. [Логирование](#6-логирование)
7. [Обработка ошибок](#7-обработка-ошибок)
8. [Тестирование](#8-тестирование)
9. [Примеры лучших практик](#9-примеры-лучших-практик)

## 1. Форматирование кода

### 1.1. Основные правила

- Используйте **4 пробела** для отступов, не табуляцию.
- Максимальная длина строки: **100 символов**.
- Используйте пустые строки для разделения логических блоков кода.
- Используйте двойные кавычки (`"`) для строк, если строка не содержит двойных кавычек.
- Используйте f-строки для форматирования строк.

### 1.2. Автоматическое форматирование

Проект использует следующие инструменты для автоматического форматирования:

- **black**: форматирование кода.
- **isort**: сортировка импортов.
- **flake8**: проверка стиля кода.

Настройки этих инструментов находятся в файлах `.flake8` и `pyproject.toml`.

### 1.3. Примеры форматирования

#### Правильно:

```python
def calculate_total(items: list[float], tax_rate: float = 0.2) -> float:
    """Вычисляет общую сумму с учетом налога."""
    subtotal = sum(items)
    tax = subtotal * tax_rate
    total = subtotal + tax

    return total


def process_user_data(user_id: int, data: dict[str, Any]) -> User | None:
    """Обрабатывает данные пользователя."""
    if not data:
        return None

    # Обработка данных
    processed_data = {
        "id": user_id,
        "name": data.get("name", "Неизвестно"),
        "email": data.get("email", ""),
        "settings": {
            "theme": data.get("theme", "default"),
            "notifications": data.get("notifications", True),
        },
    }

    return User(**processed_data)
```

#### Неправильно:

```python
def calculate_total(items,tax_rate = 0.2):
    subtotal = sum(items)
    tax = subtotal*tax_rate
    total = subtotal+tax
    return total

def process_user_data(user_id,data):
    if not data: return None
    # Обработка данных
    processed_data = {'id':user_id,'name':data.get('name','Неизвестно'),'email':data.get('email',''),'settings':{'theme':data.get('theme','default'),'notifications':data.get('notifications',True)}}
    return User(**processed_data)

## 2. Именование

### 2.1. Общие правила

- Используйте осмысленные имена, отражающие назначение.
- Избегайте сокращений, кроме общепринятых (например, `id`, `url`).
- Все имена должны быть на английском языке.
- Комментарии и документация должны быть на русском языке.

### 2.2. Соглашения по именованию

| Тип | Стиль | Пример |
|-----|-------|--------|
| Переменные | `snake_case` | `user_name`, `item_count` |
| Функции | `snake_case` | `get_user()`, `calculate_total()` |
| Методы | `snake_case` | `save_to_database()`, `get_by_id()` |
| Классы | `CamelCase` | `UserManager`, `DatabaseConnection` |
| Константы | `UPPER_CASE` | `MAX_RETRY_COUNT`, `DEFAULT_TIMEOUT` |
| Модули | `snake_case` | `user_manager.py`, `database_utils.py` |
| Пакеты | `snake_case` | `data_processing`, `api_client` |

### 2.3. Примеры именования

#### Правильно:

```python
# Константы
MAX_RETRY_COUNT = 3
DEFAULT_TIMEOUT = 30.0
API_BASE_URL = "https://api.example.com"

# Переменные
user_name = "John"
item_count = 42
is_active = True

# Функции
def get_user_by_id(user_id: int) -> User | None:
    pass

def calculate_total_price(items: list[Item], discount: float = 0.0) -> float:
    pass

# Классы
class UserManager:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_user(self, user_id: int) -> User | None:
        pass

# Исключения
class DatabaseConnectionError(Exception):
    pass
```

#### Неправильно:

```python
# Константы
maxRetryCount = 3
Default_Timeout = 30.0
apibaseurl = "https://api.example.com"

# Переменные
UserName = "John"
ItemCount = 42
isactive = True

# Функции
def GetUserById(userId):
    pass

def calc_price(i, d = 0.0):
    pass

# Классы
class user_manager:
    def __init__(self, db):
        self.db = db

    def getUser(self, user_id):
        pass

# Исключения
class databaseError(Exception):
    pass
```

## 3. Импорты

### 3.1. Порядок импортов

Импорты должны быть сгруппированы в следующем порядке:

1. Стандартные библиотеки Python
2. Сторонние библиотеки
3. Локальные импорты (из текущего проекта)

Между группами должна быть пустая строка.

### 3.2. Сортировка импортов

Используйте `isort` для автоматической сортировки импортов. Настройки находятся в `pyproject.toml`.

### 3.3. Примеры импортов

#### Правильно:

```python
# Стандартные библиотеки
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

# Сторонние библиотеки
import aiohttp
import discord
from discord.ext import commands

# Локальные импорты
from utils.database import Database
from utils.error_handler import command_error_handler
from utils.music.player import MusicPlayer
```

#### Неправильно:

```python
import discord
from utils.database import Database
import json
from discord.ext import commands
import logging
from utils.error_handler import command_error_handler
import asyncio
from datetime import datetime
from utils.music.player import MusicPlayer
from pathlib import Path
import aiohttp
from typing import Dict, List, Optional, Union
```

## 4. Типизация

### 4.1. Основные правила

- Используйте аннотации типов для всех публичных функций и методов.
- Используйте модуль `typing` для сложных типов.
- Используйте `Optional[тип]` для параметров, которые могут быть None.
- Используйте `Union[тип1, тип2]` для параметров, которые могут быть разных типов.
- Используйте `Any` только в крайнем случае.

### 4.2. Типы для часто используемых объектов

| Объект | Тип |
|--------|-----|
| Discord Bot | `commands.Bot` |
| Discord Context | `commands.Context` |
| Discord Interaction | `discord.Interaction` |
| Discord Member | `discord.Member` |
| Discord User | `discord.User` |
| Discord Message | `discord.Message` |
| Discord Channel | `discord.TextChannel | discord.VoiceChannel | discord.Thread` |
| Словарь с произвольными ключами и значениями | `dict[str, Any]` |
| Список объектов определенного типа | `list[тип]` |
| Опциональный параметр | `тип | None` |
| Функция без возвращаемого значения | `-> None` |
| Асинхронная функция | `async def function() -> тип_возврата:` |

### 4.3. Примеры типизации

#### Правильно:

```python
from typing import Any, TypedDict, Callable

# Простые функции
def get_user_name(user_id: int) -> str:
    pass

# Функции с опциональными параметрами
def get_user(user_id: int, include_details: bool = False) -> dict[str, Any] | None:
    pass

# Функции с Union типами
def process_input(data: str | dict[str, Any] | list[int]) -> dict[str, Any]:
    pass

# Асинхронные функции
async def fetch_data(url: str, timeout: float = 10.0) -> dict[str, Any] | None:
    pass

# TypedDict для словарей с известной структурой
class UserData(TypedDict):
    id: int
    name: str
    email: str | None
    is_active: bool

def create_user(data: UserData) -> User:
    pass

# Callable для функций обратного вызова
def register_callback(callback: Callable[[int, str], None]) -> None:
    pass
```

#### Неправильно:

```python
# Без типизации
def get_user_name(user_id):
    pass

# Неполная типизация
def get_user(user_id: int, include_details = False):
    pass

# Использование Any без необходимости
def process_input(data: Any) -> Any:
    pass

# Отсутствие типизации для асинхронных функций
async def fetch_data(url, timeout = 10.0):
    pass
```

## 5. Документация

### 5.1. Docstrings

- Используйте Google style для docstrings.
- Документируйте все публичные классы, методы и функции.
- Документируйте параметры, возвращаемые значения и исключения.
- Добавляйте примеры использования для сложных функций.
- Вся документация должна быть на русском языке.

### 5.2. Структура docstring

```python
def function_name(param1: type1, param2: type2) -> return_type:
    """
    Краткое описание функции (одна строка).

    Подробное описание функции, которое может занимать
    несколько строк и объяснять, что делает функция,
    как она работает и для чего используется.

    Args:
        param1: Описание первого параметра.
        param2: Описание второго параметра.

    Returns:
        Описание возвращаемого значения.

    Raises:
        ExceptionType: Описание условий, при которых возникает исключение.

    Examples:
        >>> function_name(1, "test")
        "результат"

        >>> function_name(2, "example")
        "другой результат"
    """
```

### 5.3. Примеры документации

#### Правильно:

```python
def calculate_statistics(data: list[float], exclude_outliers: bool = False) -> dict[str, float]:
    """
    Вычисляет статистические показатели для списка чисел.

    Вычисляет среднее, медиану, стандартное отклонение и другие
    статистические показатели для предоставленного списка чисел.

    Args:
        data: Список чисел для анализа.
        exclude_outliers: Если True, выбросы будут исключены из расчетов.

    Returns:
        Словарь со статистическими показателями:
        {
            "mean": среднее значение,
            "median": медиана,
            "std_dev": стандартное отклонение
        }

    Raises:
        ValueError: Если список пуст или содержит не числовые значения.

    Examples:
        >>> calculate_statistics([1, 2, 3, 4, 5])
        {'mean': 3.0, 'median': 3.0, 'std_dev': 1.58}

        >>> calculate_statistics([1, 2, 3, 100], exclude_outliers=True)
        {'mean': 2.0, 'median': 2.0, 'std_dev': 1.0}
    """
    pass

class DatabaseConnection:
    """
    Управляет подключением к базе данных.

    Предоставляет методы для выполнения запросов к базе данных,
    управления транзакциями и обработки ошибок подключения.
    """

    def __init__(self, connection_string: str, max_connections: int = 10) -> None:
        """
        Инициализирует подключение к базе данных.

        Args:
            connection_string: Строка подключения к базе данных.
            max_connections: Максимальное количество одновременных подключений.

        Raises:
            ConnectionError: Если не удалось установить подключение к базе данных.
        """
        pass

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Выполняет SQL-запрос к базе данных.

        Args:
            query: SQL-запрос для выполнения.
            params: Параметры запроса для подстановки.

        Returns:
            Список словарей с результатами запроса.

        Raises:
            QueryError: Если запрос содержит синтаксические ошибки.
            DatabaseError: Если произошла ошибка при выполнении запроса.
        """
        pass
```

#### Неправильно:

```python
def calculate_statistics(data, exclude_outliers=False):
    # Вычисляет статистику
    pass

class DatabaseConnection:
    def __init__(self, connection_string, max_connections=10):
        # Инициализация
        pass

    async def execute_query(self, query, params=None):
        # Выполняет запрос
        pass
```

## 6. Логирование

### 6.1. Настройка логгеров

- Используйте иерархические логгеры для всех модулей.
- Основной логгер: `"bot"`.
- Подсистемы: `"bot.music"`, `"bot.dota"`, `"bot.database"` и т.д.

### 6.2. Уровни логирования

- `DEBUG`: Детальная отладочная информация.
- `INFO`: Подтверждение, что все работает как ожидается.
- `WARNING`: Индикация потенциальных проблем.
- `ERROR`: Ошибки, которые не препятствуют работе программы.
- `CRITICAL`: Критические ошибки, которые могут привести к остановке программы.

### 6.3. Примеры логирования

#### Правильно:

```python
import logging

logger = logging.getLogger("bot.music")

def play_track(track_url: str) -> bool:
    """Воспроизводит трек по URL."""
    logger.debug(f"Попытка воспроизведения трека: {track_url}")
    try:
        # Логика воспроизведения
        logger.info(f"Трек успешно воспроизводится: {track_url}")
        return True
    except ConnectionError as e:
        logger.warning(f"Проблемы с подключением при воспроизведении трека {track_url}: {e}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при воспроизведении трека {track_url}: {e}", exc_info=True)
        return False

class MusicPlayer:
    def __init__(self, bot) -> None:
        self.bot = bot
        logger.info("Музыкальный плеер инициализирован")

    def __del__(self) -> None:
        logger.debug("Музыкальный плеер уничтожен")
```

#### Неправильно:

```python
def play_track(track_url):
    print(f"Попытка воспроизведения трека: {track_url}")
    try:
        # Логика воспроизведения
        print(f"Трек успешно воспроизводится: {track_url}")
        return True
    except Exception as e:
        print(f"Ошибка: {e}")
        return False

class MusicPlayer:
    def __init__(self, bot):
        self.bot = bot
        print("Музыкальный плеер инициализирован")
```

## 7. Обработка ошибок

### 7.1. Общие правила

- Используйте специфические исключения вместо общих.
- Обрабатывайте исключения как можно ближе к месту их возникновения.
- Логируйте исключения с контекстом.
- Используйте декоратор `@command_error_handler` для всех команд.

### 7.2. Примеры обработки ошибок

#### Правильно:

```python
from utils.error_handler import command_error_handler

@commands.hybrid_command(name="play", description="Воспроизвести музыку")
@command_error_handler
async def play(self, ctx: commands.Context, query: str) -> None:
    """Воспроизводит музыку по запросу."""
    # Реализация команды
    pass

def get_user_data(user_id: int) -> dict[str, Any]:
    """Получает данные пользователя из базы данных."""
    try:
        # Запрос к базе данных
        return result
    except ConnectionError as e:
        logger.error(f"Ошибка подключения к БД при получении данных пользователя {user_id}: {e}")
        raise DatabaseConnectionError(f"Не удалось подключиться к базе данных: {e}") from e
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении данных пользователя {user_id}: {e}", exc_info=True)
        raise
```

#### Неправильно:

```python
@commands.hybrid_command(name="play", description="Воспроизвести музыку")
async def play(self, ctx, query):
    try:
        # Реализация команды
        pass
    except Exception as e:
        await ctx.send(f"Произошла ошибка: {e}")

def get_user_data(user_id):
    try:
        # Запрос к базе данных
        return result
    except Exception:
        return None
```

## 8. Тестирование

### 8.1. Общие правила

- Все публичные функции и методы должны быть покрыты тестами.
- Используйте pytest и pytest-asyncio для тестирования.
- Используйте фикстуры для общих объектов.
- Используйте параметризацию для тестирования разных входных данных.
- Используйте mock/monkeypatch для изоляции от внешних зависимостей.

### 8.2. Структура тестов

- Тесты должны быть организованы в соответствии со структурой проекта.
- Имена тестовых файлов должны начинаться с `test_`.
- Имена тестовых функций должны начинаться с `test_`.
- Тесты классов могут быть организованы в классы, начинающиеся с `Test`.

### 8.3. Примеры тестов

#### Правильно:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from utils.database import Database, DatabaseError

# Фикстуры
@pytest.fixture
def mock_connection():
    """Создает мок для подключения к базе данных."""
    connection = MagicMock()
    connection.execute = MagicMock(return_value={"id": 1, "name": "Test"})
    return connection

# Тесты функций
def test_calculate_total():
    """Тестирует функцию расчета общей суммы."""
    result = calculate_total([10, 20, 30])
    assert result == 60

def test_calculate_total_empty():
    """Тестирует функцию расчета общей суммы с пустым списком."""
    result = calculate_total([])
    assert result == 0

# Параметризованные тесты
@pytest.mark.parametrize("items,expected", [
    ([10, 20, 30], 60),
    ([], 0),
    ([5], 5),
])
def test_calculate_total_parametrized(items, expected):
    """Тестирует функцию расчета общей суммы с разными входными данными."""
    result = calculate_total(items)
    assert result == expected

# Тесты исключений
def test_calculate_total_invalid():
    """Тестирует, что функция выбрасывает исключение при неверных входных данных."""
    with pytest.raises(ValueError):
        calculate_total(["a", "b", "c"])

# Тесты классов
class TestDatabase:
    """Тесты для класса Database."""

    def test_initialization(self, mock_connection):
        """Тестирует инициализацию базы данных."""
        db = Database(mock_connection)
        assert db.connection == mock_connection

    def test_get_user(self, mock_connection):
        """Тестирует получение пользователя."""
        db = Database(mock_connection)
        user = db.get_user(1)
        assert user["id"] == 1
        assert user["name"] == "Test"
        mock_connection.execute.assert_called_once()

    def test_get_user_error(self, mock_connection):
        """Тестирует обработку ошибок при получении пользователя."""
        mock_connection.execute.side_effect = Exception("DB Error")
        db = Database(mock_connection)
        with pytest.raises(DatabaseError):
            db.get_user(1)

# Асинхронные тесты
@pytest.mark.asyncio
async def test_async_function():
    """Тестирует асинхронную функцию."""
    result = await async_function()
    assert result == "expected"

# Моки и патчи
def test_function_with_external_dependency():
    """Тестирует функцию с внешней зависимостью."""
    with patch("module.external_function") as mock_external:
        mock_external.return_value = "mocked_result"
        result = function_with_external_dependency()
        assert result == "mocked_result"
        mock_external.assert_called_once()
```

## 9. Примеры лучших практик

### 9.1. Структура модуля

```python
"""Модуль для работы с базой данных."""

import logging
from typing import Any

logger = logging.getLogger("bot.database")

class DatabaseError(Exception):
    """Базовое исключение для ошибок базы данных."""
    pass

class ConnectionError(DatabaseError):
    """Исключение для ошибок подключения к базе данных."""
    pass

class QueryError(DatabaseError):
    """Исключение для ошибок выполнения запросов."""
    pass

class Database:
    """
    Управляет подключением к базе данных и выполнением запросов.

    Предоставляет методы для выполнения запросов к базе данных,
    управления транзакциями и обработки ошибок подключения.
    """

    def __init__(self, connection_string: str) -> None:
        """
        Инициализирует подключение к базе данных.

        Args:
            connection_string: Строка подключения к базе данных.

        Raises:
            ConnectionError: Если не удалось установить подключение к базе данных.
        """
        self.connection_string = connection_string
        self.connection = None
        logger.info("Инициализация подключения к базе данных")
        try:
            self.connection = self._connect()
            logger.info("Подключение к базе данных установлено")
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}", exc_info=True)
            raise ConnectionError(f"Не удалось подключиться к базе данных: {e}") from e

    def _connect(self):
        """
        Устанавливает подключение к базе данных.

        Returns:
            Объект подключения к базе данных.

        Raises:
            ConnectionError: Если не удалось установить подключение к базе данных.
        """
        # Реализация подключения
        pass

    def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Выполняет SQL-запрос к базе данных.

        Args:
            query: SQL-запрос для выполнения.
            params: Параметры запроса для подстановки.

        Returns:
            Список словарей с результатами запроса.

        Raises:
            QueryError: Если запрос содержит синтаксические ошибки.
            ConnectionError: Если произошла ошибка подключения к базе данных.
        """
        logger.debug(f"Выполнение запроса: {query}")
        try:
            result = self.connection.execute(query, params)
            logger.debug(f"Запрос выполнен успешно, получено {len(result)} записей")
            return result
        except Exception as e:
            logger.error(f"Ошибка выполнения запроса: {e}", exc_info=True)
            raise QueryError(f"Ошибка выполнения запроса: {e}") from e

    def close(self) -> None:
        """
        Закрывает подключение к базе данных.

        Raises:
            ConnectionError: Если произошла ошибка при закрытии подключения.
        """
        logger.info("Закрытие подключения к базе данных")
        try:
            if self.connection:
                self.connection.close()
                logger.info("Подключение к базе данных закрыто")
        except Exception as e:
            logger.error(f"Ошибка закрытия подключения к базе данных: {e}", exc_info=True)
            raise ConnectionError(f"Ошибка закрытия подключения к базе данных: {e}") from e
```

### 9.2. Структура кога

```python
"""Ког для управления музыкальным плеером."""

import logging
from typing import Any

import discord
from discord.ext import commands

from utils.error_handler import command_error_handler
from utils.music.player import MusicPlayer

logger = logging.getLogger("bot.cogs.music")

class MusicCog(commands.Cog, name="Музыка"):
    """
    Управляет воспроизведением музыки в голосовых каналах.

    Предоставляет команды для воспроизведения музыки, управления очередью,
    паузы, пропуска треков и остановки воспроизведения.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        Инициализирует музыкальный ког.

        Args:
            bot: Экземпляр бота.
        """
        self.bot = bot
        self.player = MusicPlayer(bot)
        logger.info("Музыкальный ког инициализирован")

    @commands.hybrid_command(name="play", description="Воспроизвести музыку")
    @command_error_handler
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """
        Воспроизводит музыку по запросу.

        Args:
            ctx: Контекст команды.
            query: Запрос для поиска музыки (URL или текст).
        """
        # Реализация команды
        pass

async def setup(bot: commands.Bot) -> None:
    """
    Добавляет ког к боту.

    Args:
        bot: Экземпляр бота.
    """
    await bot.add_cog(MusicCog(bot))
    logger.info("Музыкальный ког добавлен к боту")
```
