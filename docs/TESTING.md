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
9. [CI/CD](#9-cicd)
10. [Рекомендации по написанию тестов](#10-рекомендации-по-написанию-тестов)
11. [Примеры тестов](#11-примеры-тестов)

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
- `tests/conftest.py` - общие фикстуры для всех тестов
- `tests/test_*.py` - тесты для модулей в корне проекта

Имена тестовых файлов должны начинаться с `test_` и соответствовать именам тестируемых модулей. Например, тесты для модуля `utils/database.py` должны находиться в файле `tests/test_utils/test_database.py`.

Имена тестовых функций также должны начинаться с `test_` и описывать, что именно тестируется. Например, `test_execute_query_success` или `test_execute_query_error`.

## 3. Фикстуры

Фикстуры - это функции, которые предоставляют данные или объекты для тестов. Они определены в файле `conftest.py` и автоматически доступны во всех тестах.

### Рекомендуемое содержимое файла conftest.py

```python
"""Конфигурационный файл для pytest, содержит общие фикстуры и хуки."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

# Добавляем корень проекта в sys.path для корректного импорта модулей
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


@pytest.fixture
def mock_bot():
    """Создает мок бота Discord."""
    bot = MagicMock(spec=commands.Bot)
    bot.user = MagicMock(spec=discord.User)
    bot.user.id = 123456789
    bot.user.name = "Test Bot"
    bot.user.display_name = "Test Bot"
    bot.config = {
        "BOT_TOKEN": "fake_token",
        "STRATZ_API_KEY": "fake_api_key",
        "PREFIX": "!",
        "REPORT_CHANNEL_ID": 573665353327181824,
        "ANIME_CHANNEL_ID": 298811309640646666,
    }
    return bot


@pytest.fixture
def mock_guild():
    """Создает мок гильдии Discord."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 111222333
    guild.name = "Test Guild"
    guild.me = MagicMock(spec=discord.Member)
    guild.me.id = 123456789
    guild.me.name = "Test Bot"
    guild.me.display_name = "Test Bot"
    return guild


@pytest.fixture
def mock_member(mock_guild):
    """Создает мок участника Discord."""
    member = MagicMock(spec=discord.Member)
    member.id = 987654321
    member.name = "Test User"
    member.display_name = "Test User"
    member.mention = "<@987654321>"
    member.guild = mock_guild
    return member


@pytest.fixture
def mock_text_channel(mock_guild):
    """Создает мок текстового канала Discord."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 444555666
    channel.name = "test-channel"
    channel.guild = mock_guild
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def mock_voice_channel(mock_guild):
    """Создает мок голосового канала Discord."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 777888999
    channel.name = "test-voice-channel"
    channel.guild = mock_guild
    channel.members = []
    return channel


@pytest.fixture
def mock_message(mock_member, mock_text_channel):
    """Создает мок сообщения Discord."""
    message = MagicMock(spec=discord.Message)
    message.id = 123123123
    message.content = "!test"
    message.author = mock_member
    message.guild = mock_member.guild
    message.channel = mock_text_channel
    return message


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
    interaction.guild_id = mock_member.guild.id
    interaction.guild = mock_member.guild
    interaction.channel_id = mock_text_channel.id
    interaction.channel = mock_text_channel
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


@pytest.fixture
def mock_voice_client(mock_bot, mock_voice_channel):
    """Создает мок голосового клиента Discord."""
    voice_client = MagicMock(spec=discord.VoiceClient)
    voice_client.is_connected = MagicMock(return_value=True)
    voice_client.is_playing = MagicMock(return_value=False)
    voice_client.is_paused = MagicMock(return_value=False)
    voice_client.play = MagicMock()
    voice_client.pause = MagicMock()
    voice_client.resume = MagicMock()
    voice_client.stop = MagicMock()
    voice_client.disconnect = AsyncMock()
    voice_client.move_to = AsyncMock()
    voice_client.channel = mock_voice_channel
    return voice_client


@pytest.fixture
def mock_db():
    """Создает мок базы данных."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.fetchall = AsyncMock(return_value=[])
    db.fetchone = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    return db
```

### Использование фикстур

Фикстуры можно использовать в тестах, указав их в качестве аргументов функции теста:

```python
def test_function(mock_bot, mock_context):
    # Использование фикстур mock_bot и mock_context
    assert mock_bot.user.id == 123456789
    assert mock_context.author.id == 987654321
```

## 4. Моки и патчи

Моки и патчи используются для изоляции тестируемого кода от внешних зависимостей. В Python для этого используется модуль `unittest.mock`.

### Создание моков

```python
from unittest.mock import MagicMock, AsyncMock

# Создание обычного мока
mock_obj = MagicMock()
mock_obj.method.return_value = "expected_value"

# Создание асинхронного мока
async_mock = AsyncMock()
async_mock.method.return_value = "expected_value"
```

### Использование патчей

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

Параметризованные тесты позволяют запускать один и тот же тест с разными входными данными. Это полезно для тестирования функций с различными входными параметрами.

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
```

## 6. Асинхронное тестирование

Для тестирования асинхронных функций используется расширение `pytest-asyncio`. Тесты асинхронных функций должны быть помечены декоратором `@pytest.mark.asyncio` и определены как `async def`.

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_function_under_test()
    assert result == "expected_value"
```

## 7. Запуск тестов

### Запуск всех тестов

```bash
pytest
```

### Запуск тестов с подробным выводом

```bash
pytest -v
```

### Запуск конкретного теста

```bash
pytest tests/test_utils/test_database.py
```

### Запуск тестов, соответствующих шаблону

```bash
pytest -k "database"  # Запуск всех тестов, содержащих "database" в имени
```

### Запуск тестов с выводом print-сообщений

```bash
pytest -v -s
```

## 8. Измерение покрытия кода

Для измерения покрытия кода тестами используется расширение `pytest-cov`.

### Запуск тестов с измерением покрытия

```bash
pytest --cov=./
```

### Запуск тестов с генерацией отчета о покрытии

```bash
pytest --cov=./ --cov-report=html
```

После запуска этой команды отчет о покрытии будет доступен в директории `htmlcov/`.

### Запуск тестов с генерацией отчета о покрытии в формате XML

```bash
pytest --cov=./ --cov-report=xml:coverage/coverage.xml
```

## 9. CI/CD

Проект использует GitHub Actions для автоматизации тестирования. Конфигурация находится в файле `.github/workflows/ci.yml`.

При каждом пуше в ветки `main` и `dev`, а также при создании пул-реквеста в эти ветки, автоматически запускаются следующие проверки:

1. Линтинг кода с помощью flake8
2. Проверка форматирования с помощью black
3. Проверка порядка импортов с помощью isort
4. Проверка типов с помощью mypy
5. Запуск тестов с помощью pytest и генерация отчета о покрытии

### Рекомендуемые улучшения CI/CD

1. Добавить загрузку отчета о покрытии в Codecov или аналогичный сервис:

```yaml
- name: Upload coverage to Codecov
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage/coverage.xml
    fail_ci_if_error: true
```

2. Добавить кэширование зависимостей для ускорения сборки:

```yaml
- name: Cache pip dependencies
  uses: actions/cache@v3
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('**/pyproject.toml') }}
    restore-keys: |
      ${{ runner.os }}-pip-
```

## 10. Рекомендации по написанию тестов

### Общие рекомендации

1. **Тестируйте только публичный API** - тестируйте только публичные функции и методы, не тестируйте внутренние детали реализации.
2. **Один тест - одна функциональность** - каждый тест должен проверять только одну функциональность.
3. **Используйте моки для изоляции** - используйте моки для изоляции тестируемого кода от внешних зависимостей.
4. **Используйте параметризацию** - используйте параметризацию для тестирования функций с разными входными данными.
5. **Тестируйте граничные случаи** - тестируйте граничные случаи и обработку ошибок.

### Рекомендации для тестирования когов

1. **Тестируйте инициализацию кога** - проверяйте, что ког корректно инициализируется.
2. **Тестируйте команды** - проверяйте, что команды корректно регистрируются и выполняются.
3. **Тестируйте обработку ошибок** - проверяйте, что ошибки корректно обрабатываются.
4. **Используйте моки для Discord API** - используйте моки для имитации взаимодействия с Discord API.

### Рекомендации для тестирования утилит

1. **Тестируйте публичные функции** - тестируйте все публичные функции и методы.
2. **Тестируйте граничные случаи** - тестируйте граничные случаи и обработку ошибок.
3. **Используйте параметризацию** - используйте параметризацию для тестирования функций с разными входными данными.

### Рекомендации для тестирования обработчиков событий

1. **Тестируйте обработку событий** - проверяйте, что события корректно обрабатываются.
2. **Используйте моки для событий** - используйте моки для имитации событий Discord.
3. **Тестируйте обработку ошибок** - проверяйте, что ошибки корректно обрабатываются.

## 11. Примеры тестов

### Пример теста для утилиты

```python
import pytest
from unittest.mock import MagicMock, patch

from utils.database import Database

@pytest.mark.asyncio
async def test_execute_query_success(mock_db):
    # Настройка мока
    mock_db.execute.return_value = None
    mock_db.fetchall.return_value = [{"id": 1, "name": "Test"}]

    # Создание экземпляра Database с моком
    db = Database(mock_db)

    # Вызов тестируемой функции
    result = await db.execute_query("SELECT * FROM test")

    # Проверка результата
    assert result == [{"id": 1, "name": "Test"}]
    mock_db.execute.assert_called_once_with("SELECT * FROM test")
    mock_db.fetchall.assert_called_once()

@pytest.mark.asyncio
async def test_execute_query_error(mock_db):
    # Настройка мока для имитации ошибки
    mock_db.execute.side_effect = Exception("Database error")

    # Создание экземпляра Database с моком
    db = Database(mock_db)

    # Проверка, что функция выбрасывает исключение
    with pytest.raises(Exception) as excinfo:
        await db.execute_query("SELECT * FROM test")

    # Проверка сообщения об ошибке
    assert "Database error" in str(excinfo.value)
```

### Пример теста для кога

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.admin import AdminCog

@pytest.fixture
def admin_cog(mock_bot):
    return AdminCog(mock_bot)

def test_admin_cog_init(admin_cog, mock_bot):
    assert isinstance(admin_cog, AdminCog)
    assert admin_cog.bot == mock_bot

@pytest.mark.asyncio
async def test_clear_command(admin_cog, mock_context):
    # Настройка мока
    mock_context.channel.purge = AsyncMock(return_value=[MagicMock() for _ in range(5)])

    # Вызов тестируемой функции
    await admin_cog.clear(mock_context, 5)

    # Проверка результата
    mock_context.channel.purge.assert_called_once_with(limit=5)
    mock_context.send.assert_called_once()
    assert "5" in mock_context.send.call_args[0][0]
```

### Пример теста для обработчика событий

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.events import Events

@pytest.fixture
def events_cog(mock_bot):
    return Events(mock_bot)

@pytest.mark.asyncio
async def test_on_member_remove(events_cog, mock_member, mock_text_channel):
    # Настройка мока
    mock_member.guild.text_channels = [mock_text_channel]
    mock_text_channel.name = "general"

    # Вызов тестируемой функции
    await events_cog.on_member_remove(mock_member)

    # Проверка результата
    mock_text_channel.send.assert_called_once()
    assert mock_member.name in mock_text_channel.send.call_args[0][0]
