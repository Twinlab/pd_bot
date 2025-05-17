# CONTRIBUTING.md

## Общие правила

- Соблюдайте PEP8 (автоматически проверяется flake8, black, isort).
- Используйте аннотации типов для всех публичных функций и методов.
- Все публичные классы и функции должны иметь docstrings (Google style).
- Не используйте print для отладки — только logging.
- Для логирования используйте иерархические логгеры (см. README, раздел 7).
- Не храните чувствительные данные и большие файлы в репозитории (data/, downloads/, logs/).
- Все комментарии и документация должны быть на русском языке.

## Архитектура

- Все команды и события — только в cogs (наследники commands.Cog).
- Вся бизнес-логика и утилиты — только в utils.
- Обработчики glue-кода и событий Discord — только в handlers.
- Повторяющиеся паттерны выносите в базовые классы или утилиты.
- Каждый модуль должен иметь единственную ответственность (принцип SRP).
- Используйте инъекцию зависимостей вместо прямого создания объектов.

### Структура модулей

#### Cogs
```python
"""Описание кога и его назначения."""

import logging
from typing import Any

import discord
from discord.ext import commands

from utils.error_handler import command_error_handler

logger = logging.getLogger("bot.cogs.имя_кога")

class ИмяКога(commands.Cog, name="Отображаемое имя"):
    """
    Подробное описание кога.

    Описывает основное назначение и функциональность.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        Инициализирует ког.

        Args:
            bot: Экземпляр бота.
        """
        self.bot = bot
        logger.info("Ког инициализирован")

    @commands.hybrid_command(name="имя_команды", description="Описание команды")
    @command_error_handler
    async def имя_команды(self, ctx: commands.Context, параметр: тип) -> None:
        """
        Описание команды.

        Args:
            ctx: Контекст команды.
            параметр: Описание параметра.
        """
        # Реализация команды
        pass

async def setup(bot: commands.Bot) -> None:
    """
    Добавляет ког к боту.

    Args:
        bot: Экземпляр бота.
    """
    await bot.add_cog(ИмяКога(bot))
    logger.info("Ког добавлен к боту")
```

#### Utils
```python
"""Описание утилиты и её назначения."""

import logging
from typing import Any

logger = logging.getLogger("bot.utils.имя_модуля")

def имя_функции(параметр: тип) -> тип_возврата:
    """
    Описание функции.

    Args:
        параметр: Описание параметра.

    Returns:
        Описание возвращаемого значения.

    Raises:
        ТипИсключения: Описание условий возникновения исключения.
    """
    # Реализация функции
    pass

class ИмяКласса:
    """
    Описание класса.

    Подробное описание назначения и функциональности класса.
    """

    def __init__(self, параметр: тип) -> None:
        """
        Инициализирует класс.

        Args:
            параметр: Описание параметра.
        """
        self.параметр = параметр
        logger.debug("Класс инициализирован")

    def метод(self, параметр: тип) -> тип_возврата:
        """
        Описание метода.

        Args:
            параметр: Описание параметра.

        Returns:
            Описание возвращаемого значения.
        """
        # Реализация метода
        pass
```

## Стиль кода

Более подробную информацию о стандартах кода, включая специфические правила и примеры, можно найти в нашем [Руководстве по стилю кода (STYLE_GUIDE.md)](./STYLE_GUIDE.md).
### Форматирование

- Максимальная длина строки: 100 символов (настроено в black и flake8).
- Отступы: 4 пробела (настроено в black).
- Используйте двойные кавычки для строк, если строка не содержит двойных кавычек.
- Используйте f-строки вместо `.format()` или `%`.

#### Правильно:
```python
def get_user_info(user_id: int) -> dict[str, Any]:
    """Получает информацию о пользователе."""
    logger.info(f"Запрос информации о пользователе {user_id}")
    return {"id": user_id, "name": "Пользователь"}
```

#### Неправильно:
```python
def get_user_info(user_id):
    print("Запрос информации о пользователе %s" % user_id)
    return {'id': user_id, 'name': 'Пользователь'}
```

### Именование

- Используйте `snake_case` для переменных, функций и методов.
- Используйте `CamelCase` для классов.
- Используйте `UPPER_CASE` для констант.
- Используйте осмысленные имена, отражающие назначение.

#### Правильно:
```python
MAX_RETRY_COUNT = 3

class UserManager:
    def get_user_by_id(self, user_id: int) -> User | None:
        pass
```

#### Неправильно:
```python
max = 3

class usermanager:
    def getUserById(self, userId):
        pass
```

### Типизация

- Используйте аннотации типов для всех публичных функций и методов.
- Используйте `тип | None` для параметров, которые могут быть None.
- Используйте `тип1 | тип2` для параметров, которые могут быть разных типов.
- Используйте `Any` только в крайнем случае.
- Используйте `typing.TypedDict` для словарей с известной структурой.
- Используйте `typing.Protocol` для структурной типизации.

#### Правильно:
```python
from typing import Any

def process_data(data: str | dict[str, Any]) -> list[int] | None:
    """Обрабатывает данные и возвращает список чисел или None."""
    pass
```

#### Неправильно:
```python
def process_data(data):
    pass
```

## Документация

### Docstrings

- Используйте Google style для docstrings.
- Документируйте все публичные классы, методы и функции.
- Документируйте параметры, возвращаемые значения и исключения.
- Добавляйте примеры использования для сложных функций.
- Вся документация должна быть на русском языке.

#### Пример:
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
```

## Логирование

- Используйте иерархические логгеры для всех модулей.
- Основной логгер: `"bot"`.
- Подсистемы: `"bot.music"`, `"bot.dota"`, `"bot.database"` и т.д.
- Используйте соответствующие уровни логирования:
  - `DEBUG`: Детальная отладочная информация.
  - `INFO`: Подтверждение, что все работает как ожидается.
  - `WARNING`: Индикация потенциальных проблем.
  - `ERROR`: Ошибки, которые не препятствуют работе программы.
  - `CRITICAL`: Критические ошибки, которые могут привести к остановке программы.

### Пример:
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
    except Exception as e:
        logger.error(f"Ошибка при воспроизведении трека {track_url}: {e}", exc_info=True)
        return False
```

## Тестирование

- Все публичные функции и методы должны быть покрыты тестами.
- Используйте pytest и pytest-asyncio для тестирования.
- Используйте фикстуры для общих объектов.
- Используйте параметризацию для тестирования разных входных данных.
- Используйте mock/monkeypatch для изоляции от внешних зависимостей.
- Стремитесь к покрытию кода тестами не менее 80%.

### Структура тестов

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from utils.your_module import YourClass, your_function

# Фикстуры
@pytest.fixture
def mock_dependency():
    """Создает мок для зависимости."""
    dependency = MagicMock()
    dependency.method.return_value = "expected_value"
    return dependency

# Тесты функций
def test_your_function_success():
    """Тестирует успешное выполнение функции."""
    result = your_function(1, 2)
    assert result == 3

def test_your_function_error():
    """Тестирует обработку ошибок в функции."""
    with pytest.raises(ValueError):
        your_function(-1, 2)

# Тесты классов
class TestYourClass:
    """Тесты для YourClass."""

    def test_initialization(self, mock_dependency):
        """Тестирует инициализацию класса."""
        instance = YourClass(mock_dependency)
        assert instance.dependency == mock_dependency

    @pytest.mark.asyncio
    async def test_async_method(self, mock_dependency):
        """Тестирует асинхронный метод."""
        instance = YourClass(mock_dependency)
        with patch("module.external_function", new_callable=AsyncMock) as mock_external:
            mock_external.return_value = "mocked_result"
            result = await instance.async_method()
            assert result == "mocked_result"
            mock_external.assert_called_once()
```

## Автоматизация

- Перед коммитом запускайте pre-commit:
  ```
  pre-commit install
  git add .
  git commit -m "..."
  ```
- Все проверки (black, isort, flake8, mypy, тесты) должны проходить без ошибок.
- Для CI используйте GitHub Actions (или аналог).

### Проверки pre-commit

- black: форматирование кода.
- isort: сортировка импортов.
- flake8: проверка стиля кода.
- mypy: проверка типов.
- end-of-file-fixer: проверка наличия пустой строки в конце файла.
- trailing-whitespace: проверка отсутствия пробелов в конце строк.
- check-added-large-files: проверка размера добавляемых файлов.

## Зависимости

- requirements.txt — только runtime-зависимости.
- requirements-dev.txt — только dev-зависимости (линтеры, тесты, pre-commit и т.д.).
- Регулярно обновляйте зависимости для устранения уязвимостей.
- Указывайте конкретные версии зависимостей для воспроизводимости сборки.

## Процесс разработки

1. Создайте ветку для новой функциональности или исправления.
2. Разработайте функциональность с соблюдением всех стандартов.
3. Напишите тесты для новой функциональности.
4. Убедитесь, что все тесты проходят и все проверки pre-commit успешны.
5. Создайте pull request с описанием изменений.
6. После ревью и одобрения, изменения будут слиты в основную ветку.

## Дополнительные ресурсы

- [PEP 8 — Style Guide for Python Code](https://peps.python.org/pep-0008/)
- [PEP 484 — Type Hints](https://peps.python.org/pep-0484/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Pytest Documentation](https://docs.pytest.org/)
- [Discord.py Documentation](https://discordpy.readthedocs.io/)
