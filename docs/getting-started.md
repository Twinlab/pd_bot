# Начало работы

## Требования

- Docker и Docker Compose
- Для локальной разработки: Python 3.13+, FFmpeg

## Конфигурация

Бот использует двухуровневую систему конфигурации на основе Pydantic Settings:

- **`.env`** — секретные данные (токены, API ключи)
- **`config/bot_settings.yaml`** — основные настройки (каналы, таймауты, лимиты)

### Настройка

1. **Скопируйте `.env.example` в `.env`:**

    ```bash
    cp .env.example .env
    ```

2. **Заполните обязательные поля в `.env`:**

    - `BOT_TOKEN` — токен Discord бота
    - `STRATZ_API_KEY` — API ключ для Dota 2 (Stratz)
    - `TWITCH_CLIENT_ID` и `TWITCH_CLIENT_SECRET` — (опционально) для Twitch уведомлений

3. **При необходимости отредактируйте `config/bot_settings.yaml`:**

    - ID каналов, таймауты и другие параметры

!!! warning "Важно"
    Не добавляйте файлы `.env` и `data/bot_data.db` в Git.

## Запуск

### Docker (рекомендуется)

```bash
docker compose up -d --build
```

### Локальная разработка

```bash
# Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate

# Установить зависимости
pip install -e ".[dev]"

# Запустить бота
python main.py
```

## Разработка

### Линтинг и форматирование

```bash
ruff check .              # линтинг
ruff check --fix .        # линтинг с автофиксом
ruff format .             # форматирование
```

### Проверка типов

```bash
mypy .
```

### Тестирование

```bash
pytest                    # все тесты
pytest --cov              # с покрытием
pytest tests/test_file.py # один файл
```

### Конфигурация инструментов

Все настройки инструментов (ruff, mypy, pytest) находятся в `pyproject.toml`.

Pre-commit хуки автоматически запускают `ruff --fix` и `ruff format`. Конфигурация: `.pre-commit-config.yaml`.
