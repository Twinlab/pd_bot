# Руководство по тестированию PD Bot

## Содержание

1. [Общая информация](#1-общая-информация)
2. [Структура тестов](#2-структура-тестов)
3. [Фикстуры](#3-фикстуры)
4. [Моки и патчи](#4-моки-и-патчи)
5. [Параметризованные тесты](#5-параметризованные-тесты)
6. [Асинхронное тестирование](#6-асинхронное-тестирование)
7. [Запуск тестов](#7-запуск-тестов)
8. [Измерение покрытия кода](#8-измерение-покрытия-кода)
9. [Как писать тесты для новых модулей](#9-как-писать-тесты-для-новых-модулей)
10. [Паттерны тестирования по типам модулей](#10-паттерны-тестирования-по-типам-модулей)
11. [CI/CD](#11-cicd)
12. [Рекомендации по написанию тестов](#12-рекомендации-по-написанию-тестов)
13. [Примеры тестов](#13-примеры-тестов)

## 1. Общая информация

Проект использует следующие инструменты для тестирования:

- **pytest** - основной фреймворк для тестирования
- **pytest-asyncio** - расширение для тестирования асинхронного кода
- **pytest-cov** - расширение для измерения покрытия кода тестами
- **freezegun** - библиотека для мокирования времени
- **unittest.mock** - стандартная библиотека Python для создания моков

Все тесты находятся в директории `tests/`. Структура тестов соответствует структуре проекта.

## 2. Структура тестов

Тесты организованы в соответствии со структурой проекта:

- `tests/test_utils/` - тесты для модулей из директории `utils/`
- `tests/test_cogs/` - тесты для когов из директории `cogs/`
- `tests/test_handlers/` - тесты для обработчиков из директории `handlers/`
- `tests/conftest.py` - общие фикстуры для всех тестов
- `tests/test_*.py` - тесты для модулей в корне проекта

### Правила именования:

1. **Файлы тестов**: `test_{имя_модуля}.py`
   - Для `utils/database.py` → `tests/test_utils/test_database.py`
   - Для `cogs/music.py` → `tests/test_cogs/test_music_cog.py`

2. **Функции тестов**: `test_{что_тестируется}_{сценарий}`
   - `test_execute_query_success`
   - `test_execute_query_database_error`
   - `test_add_streamer_duplicate_username`

3. **Классы тестов**: `Test{ИмяКласса}` или `Test{Функциональность}`
   - `TestActivityDataManager`
   - `TestCommandHandling`

## 3. Фикстуры

Фикстуры - это функции, которые предоставляют данные или объекты для тестов. Они определены в файле `conftest.py` и автоматически доступны во всех тестах.

### Основные фикстуры проекта:

```python
@pytest.fixture
def mock_bot():
    """Создает мок бота Discord."""
    bot = MagicMock(spec=commands.Bot)
    bot.user = MagicMock(spec=discord.User)
    bot.user.id = 123456789
    bot.user.name = "Test Bot"
    bot.config = {
        "BOT_TOKEN": "fake_token",
        "STRATZ_API_KEY": "fake_api_key",
        "PREFIX": "!",
        "REPORT_CHANNEL_ID": 573665353327181824,
        "ANIME_CHANNEL_ID": 298811309640646666,
    }
    return bot

@pytest.fixture
def mock_context(mock_bot, mock_message):
    """Создает мок контекста команды Discord."""
    ctx = MagicMock(spec=commands.Context)
    ctx.bot = mock_bot
    ctx.author = mock_message.author
    ctx.guild = mock_message.guild
    ctx.channel = mock_message.channel
    ctx.message = mock_message
    ctx.send = AsyncMock()
    return ctx

@pytest.fixture
def mock_interaction(mock_bot, mock_member, mock_text_channel):
    """Создает мок взаимодействия Discord."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.bot = mock_bot
    interaction.user = mock_member
    interaction.guild = mock_member.guild
    interaction.channel = mock_text_channel
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction
```

### Использование фикстур:

```python
def test_function(mock_bot, mock_context):
    # Использование фикстур mock_bot и mock_context
    assert mock_bot.user.id == 123456789
    assert mock_context.author.id == 987654321
```

## 4. Моки и патчи

Моки и патчи используются для изоляции тестируемого кода от внешних зависимостей.

### Создание моков:

```python
from unittest.mock import MagicMock, AsyncMock

# Создание обычного мока
mock_obj = MagicMock()
mock_obj.method.return_value = "expected_value"

# Создание асинхронного мока
async_mock = AsyncMock()
async_mock.method.return_value = "expected_value"
```

### Использование патчей:

```python
from unittest.mock import patch

# Патч функции
@patch("module.function")
def test_function(mock_function):
    mock_function.return_value = "expected_value"
    # Тестирование кода, использующего module.function

# Патч класса
@patch("module.Class")
def test_class(MockClass):
    MockClass.return_value.method.return_value = "expected_value"
    # Тестирование кода, использующего module.Class

# Патч с контекстным менеджером
def test_with_context_manager():
    with patch("module.function") as mock_function:
        mock_function.return_value = "expected_value"
        # Тестирование кода, использующего module.function
```

## 5. Параметризованные тесты

Параметризованные тесты позволяют запускать один и тот же тест с разными входными данными.

```python
import pytest

@pytest.mark.parametrize("input_value,expected_output", [
    (1, "one"),
    (2, "two"),
    (3, "three"),
])
def test_function(input_value, expected_output):
    result = function_under_test(input_value)
    assert result == expected_output

# Параметризация с именованными параметрами
@pytest.mark.parametrize("user_id,game_name,expected_result", [
    (123, "Dota 2", True),
    (456, "CS:GO", True),
    (789, "", False),  # Пустое имя игры
])
def test_update_activity(user_id, game_name, expected_result):
    result = update_activity(user_id, game_name)
    assert bool(result) == expected_result
```

## 6. Асинхронное тестирование

Для тестирования асинхронных функций используется расширение `pytest-asyncio`.

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_function_under_test()
    assert result == "expected_value"

# Тестирование асинхронных методов с моками
@pytest.mark.asyncio
async def test_async_database_operation():
    with patch("aiosqlite.connect") as mock_connect:
        mock_db = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_db
        mock_db.execute.return_value = None
        mock_db.fetchone.return_value = {"id": 1, "name": "test"}

        result = await database_function()
        assert result["name"] == "test"
```

## 7. Запуск тестов

### Запуск всех тестов:
```bash
source .venv/bin/activate
pytest
```

### Запуск тестов с подробным выводом:
```bash
pytest -v
```

### Запуск конкретного теста:
```bash
pytest tests/test_utils/test_database.py
```

### Запуск тестов, соответствующих шаблону:
```bash
pytest -k "database"  # Запуск всех тестов, содержащих "database" в имени
```

### Запуск тестов с выводом print-сообщений:
```bash
pytest -v -s
```

## 8. Измерение покрытия кода

### Запуск тестов с измерением покрытия:
```bash
pytest --cov=./
```

### Запуск тестов с генерацией HTML отчета:
```bash
pytest --cov=./ --cov-report=html
```

После запуска отчет будет доступен в директории `htmlcov/`.

### Запуск тестов с генерацией XML отчета:
```bash
pytest --cov=./ --cov-report=xml:coverage/coverage.xml
```

## 9. Как писать тесты для новых модулей

### Шаг 1: Создание файла тестов

1. Определите тип модуля (ког, утилита, обработчик)
2. Создайте соответствующий файл в нужной директории:
   - Для `utils/new_module.py` → `tests/test_utils/test_new_module.py`
   - Для `cogs/new_cog.py` → `tests/test_cogs/test_new_cog.py`

### Шаг 2: Базовая структура теста

```python
"""Тесты для модуля new_module.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Импорт тестируемого модуля
from utils.new_module import NewClass, new_function


class TestNewClass:
    """Тесты для класса NewClass."""

    def test_init(self):
        """Тест инициализации класса."""
        instance = NewClass()
        assert isinstance(instance, NewClass)

    @pytest.mark.asyncio
    async def test_async_method(self):
        """Тест асинхронного метода."""
        instance = NewClass()
        result = await instance.async_method()
        assert result is not None


def test_new_function():
    """Тест функции new_function."""
    result = new_function("test_input")
    assert result == "expected_output"
```

### Шаг 3: Покрытие всех публичных методов

Убедитесь, что покрыты тестами:
- Все публичные методы и функции
- Различные сценарии использования (успех, ошибки)
- Граничные случаи
- Обработка исключений

### Шаг 4: Добавление специфичных тестов

В зависимости от типа модуля, добавьте соответствующие тесты (см. раздел 10).

## 10. Паттерны тестирования по типам модулей

### 10.1 Тестирование когов (Discord Cogs)

```python
"""Пример тестирования кога."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.example_cog import ExampleCog


@pytest.fixture
def example_cog(mock_bot):
    """Создает экземпляр кога для тестирования."""
    return ExampleCog(mock_bot)


class TestExampleCogInit:
    """Тесты инициализации кога."""

    def test_cog_init(self, example_cog, mock_bot):
        """Тест инициализации кога."""
        assert isinstance(example_cog, ExampleCog)
        assert example_cog.bot == mock_bot


class TestCommands:
    """Тесты команд кога."""

    @pytest.mark.asyncio
    async def test_example_command_success(self, example_cog, mock_context):
        """Тест успешного выполнения команды."""
        await example_cog.example_command(mock_context, "test_arg")

        # Проверяем, что команда отправила ответ
        mock_context.send.assert_called_once()

        # Проверяем содержимое ответа
        call_args = mock_context.send.call_args[0][0]
        assert "expected_text" in call_args

    @pytest.mark.asyncio
    async def test_example_command_error(self, example_cog, mock_context):
        """Тест обработки ошибки в команде."""
        with patch("cogs.example_cog.some_function", side_effect=Exception("Test error")):
            await example_cog.example_command(mock_context, "invalid_arg")

            # Проверяем, что отправлено сообщение об ошибке
            mock_context.send.assert_called_once()


class TestEventHandlers:
    """Тесты обработчиков событий."""

    @pytest.mark.asyncio
    async def test_on_ready(self, example_cog):
        """Тест обработчика события on_ready."""
        await example_cog.on_ready()
        # Проверяем, что необходимые действия выполнены


class TestErrorHandling:
    """Тесты обработки ошибок кога."""

    @pytest.mark.asyncio
    async def test_cog_command_error(self, example_cog, mock_context):
        """Тест обработчика ошибок команд."""
        error = Exception("Test error")
        await example_cog.cog_command_error(mock_context, error)

        # Проверяем, что ошибка обработана корректно
        mock_context.send.assert_called_once()


async def test_setup_function(mock_bot):
    """Тест функции setup кога."""
    from cogs.example_cog import setup
    await setup(mock_bot)
    mock_bot.add_cog.assert_called_once()
```

### 10.2 Тестирование утилит

```python
"""Пример тестирования утилиты."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from utils.example_utils import ExampleManager, utility_function


class TestExampleManager:
    """Тесты для класса ExampleManager."""

    @pytest.fixture
    def manager(self):
        """Создает экземпляр менеджера."""
        return ExampleManager()

    @pytest.mark.asyncio
    async def test_create_item_success(self, manager):
        """Тест успешного создания элемента."""
        with patch("aiosqlite.connect") as mock_connect:
            mock_db = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_db
            mock_db.execute.return_value = None
            mock_db.commit.return_value = None

            result = await manager.create_item("test_name", "test_value")

            assert result is True
            mock_db.execute.assert_called_once()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_item_database_error(self, manager):
        """Тест обработки ошибки базы данных."""
        with patch("aiosqlite.connect", side_effect=Exception("DB Error")):
            result = await manager.create_item("test_name", "test_value")
            assert result is False

    @pytest.mark.parametrize("name,value,expected", [
        ("valid_name", "valid_value", True),
        ("", "valid_value", False),  # Пустое имя
        ("valid_name", "", False),   # Пустое значение
        (None, "valid_value", False), # None имя
    ])
    @pytest.mark.asyncio
    async def test_create_item_validation(self, manager, name, value, expected):
        """Тест валидации входных данных."""
        with patch("aiosqlite.connect"):
            result = await manager.create_item(name, value)
            assert bool(result) == expected


def test_utility_function():
    """Тест утилитарной функции."""
    result = utility_function("input")
    assert result == "expected_output"

@pytest.mark.parametrize("input_data,expected", [
    ("normal_input", "normal_output"),
    ("", "default_output"),
    (None, "error_output"),
])
def test_utility_function_edge_cases(input_data, expected):
    """Тест граничных случаев утилитарной функции."""
    result = utility_function(input_data)
    assert result == expected
```

### 10.3 Тестирование API интеграций

```python
"""Пример тестирования API интеграции."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from utils.api_client import APIClient


class TestAPIClient:
    """Тесты для API клиента."""

    @pytest.fixture
    def api_client(self):
        """Создает экземпляр API клиента."""
        return APIClient("test_api_key")

    @pytest.mark.asyncio
    async def test_make_request_success(self, api_client):
        """Тест успешного API запроса."""
        mock_response_data = {"status": "success", "data": {"id": 1}}

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_response_data
            mock_get.return_value.__aenter__.return_value = mock_response

            result = await api_client.make_request("/test-endpoint")

            assert result == mock_response_data
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_request_http_error(self, api_client):
        """Тест обработки HTTP ошибки."""
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 404
            mock_response.text.return_value = "Not Found"
            mock_get.return_value.__aenter__.return_value = mock_response

            with pytest.raises(aiohttp.ClientResponseError):
                await api_client.make_request("/nonexistent-endpoint")

    @pytest.mark.asyncio
    async def test_make_request_network_error(self, api_client):
        """Тест обработки сетевой ошибки."""
        with patch("aiohttp.ClientSession.get", side_effect=aiohttp.ClientError("Network error")):
            result = await api_client.make_request("/test-endpoint")
            assert result is None
```

### 10.4 Тестирование обработчиков событий

```python
"""Пример тестирования обработчика событий."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.example_handler import ExampleHandler


class TestExampleHandler:
    """Тесты для обработчика событий."""

    @pytest.fixture
    def handler(self, mock_bot):
        """Создает экземпляр обработчика."""
        return ExampleHandler(mock_bot)

    @pytest.mark.asyncio
    async def test_on_message_normal(self, handler, mock_message):
        """Тест обработки обычного сообщения."""
        mock_message.author.bot = False
        mock_message.content = "Hello, world!"

        await handler.on_message(mock_message)

        # Проверяем, что сообщение обработано
        # (зависит от логики обработчика)

    @pytest.mark.asyncio
    async def test_on_message_bot_message(self, handler, mock_message):
        """Тест игнорирования сообщений от ботов."""
        mock_message.author.bot = True
        mock_message.content = "Bot message"

        await handler.on_message(mock_message)

        # Проверяем, что сообщение от бота игнорируется

    @pytest.mark.asyncio
    async def test_on_message_error_handling(self, handler, mock_message):
        """Тест обработки ошибок в обработчике."""
        mock_message.author.bot = False

        with patch("handlers.example_handler.some_function", side_effect=Exception("Test error")):
            # Обработчик не должен падать при ошибке
            await handler.on_message(mock_message)
```

## 11. CI/CD

Проект использует GitHub Actions для автоматизации тестирования. При каждом пуше и пул-реквесте автоматически запускаются:

1. Линтинг кода с помощью flake8
2. Проверка форматирования с помощью black
3. Проверка порядка импортов с помощью isort
4. Проверка типов с помощью mypy
5. Запуск тестов с помощью pytest и генерация отчета о покрытии

## 12. Рекомендации по написанию тестов

### Общие рекомендации:

1. **Тестируйте только публичный API** - тестируйте только публичные функции и методы
2. **Один тест - одна функциональность** - каждый тест должен проверять только одну функциональность
3. **Используйте моки для изоляции** - изолируйте тестируемый код от внешних зависимостей
4. **Используйте параметризацию** - тестируйте функции с разными входными данными
5. **Тестируйте граничные случаи** - тестируйте граничные случаи и обработку ошибок
6. **Понятные имена тестов** - имена должны четко описывать, что тестируется
7. **Независимые тесты** - тесты не должны зависеть друг от друга

### Что обязательно тестировать:

1. **Инициализация классов** - корректность создания экземпляров
2. **Публичные методы** - все публичные методы и функции
3. **Обработка ошибок** - корректная обработка исключений
4. **Граничные случаи** - пустые значения, None, некорректные данные
5. **Асинхронные операции** - корректность async/await
6. **Интеграции** - взаимодействие с внешними сервисами (через моки)

### Что НЕ нужно тестировать:

1. **Приватные методы** - тестируйте только через публичный API
2. **Сторонние библиотеки** - не тестируйте код библиотек
3. **Тривиальные геттеры/сеттеры** - простые свойства без логики
4. **Константы** - статические значения без логики

### Структура теста:

```python
def test_function_name():
    """Краткое описание того, что тестируется."""
    # Arrange (Подготовка)
    input_data = "test_input"
    expected_result = "expected_output"

    # Act (Действие)
    result = function_under_test(input_data)

    # Assert (Проверка)
    assert result == expected_result
```

## 13. Примеры тестов

### Пример теста для утилиты:

```python
import pytest
from unittest.mock import AsyncMock, patch

from utils.database import Database

@pytest.mark.asyncio
async def test_execute_query_success():
    """Тест успешного выполнения запроса к базе данных."""
    # Arrange
    expected_result = [{"id": 1, "name": "Test"}]

    with patch("aiosqlite.connect") as mock_connect:
        mock_db = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_db
        mock_db.execute.return_value = None
        mock_db.fetchall.return_value = expected_result

        db = Database()

        # Act
        result = await db.execute_query("SELECT * FROM test")

        # Assert
        assert result == expected_result
        mock_db.execute.assert_called_once_with("SELECT * FROM test", None)
        mock_db.fetchall.assert_called_once()

@pytest.mark.asyncio
async def test_execute_query_error():
    """Тест обработки ошибки при выполнении запроса."""
    # Arrange
    with patch("aiosqlite.connect", side_effect=Exception("Database error")):
        db = Database()

        # Act & Assert
        with pytest.raises(Exception) as excinfo:
            await db.execute_query("SELECT * FROM test")

        assert "Database error" in str(excinfo.value)
```

### Пример теста для кога:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from cogs.admin import AdminCog

@pytest.fixture
def admin_cog(mock_bot):
    return AdminCog(mock_bot)

def test_admin_cog_init(admin_cog, mock_bot):
    """Тест инициализации AdminCog."""
    assert isinstance(admin_cog, AdminCog)
    assert admin_cog.bot == mock_bot

@pytest.mark.asyncio
async def test_clear_command(admin_cog, mock_context):
    """Тест команды очистки сообщений."""
    # Arrange
    mock_context.channel.purge = AsyncMock(return_value=[MagicMock() for _ in range(5)])

    # Act
    await admin_cog.clear(mock_context, 5)

    # Assert
    mock_context.channel.purge.assert_called_once_with(limit=5)
    mock_context.send.assert_called_once()

    # Проверяем, что в ответе упоминается количество удаленных сообщений
    call_args = mock_context.send.call_args[0][0]
    assert "5" in call_args
```

### Пример теста для обработчика событий:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.events import Events

@pytest.fixture
def events_handler(mock_bot):
    return Events(mock_bot)

@pytest.mark.asyncio
async def test_on_member_remove(events_handler, mock_member, mock_text_channel):
    """Тест обработки события выхода участника."""
    # Arrange
    mock_member.guild.text_channels = [mock_text_channel]
    mock_text_channel.name = "general"

    # Act
    await events_handler.on_member_remove(mock_member)

    # Assert
    mock_text_channel.send.assert_called_once()

    # Проверяем, что в сообщении упоминается имя участника
    call_args = mock_text_channel.send.call_args[0][0]
    assert mock_member.name in call_args
```

---

Эта документация поможет разработчикам правильно писать тесты для новых модулей и изменений в существующих модулях проекта PD Bot.
