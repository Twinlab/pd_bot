# Начало работы

## Требования

- Docker и Docker Compose v2 (на продакшен-VM)
- Для разработки: Python 3.13+ (только для прогонки тестов/линта — сам бот локально не запускается, см. [Деплой](deployment.md))

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
    - `LAVALINK_SERVER_PASSWORD` — случайный пароль для Lavalink (`openssl rand -hex 32`)
    - `YOUTUBE_REFRESH_TOKEN` — OAuth refresh от burner-аккаунта Google (см. [Деплой → YouTube OAuth](deployment.md#youtube-oauth--bot-detection))
    - `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` — (опционально) для Twitch уведомлений
    - `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — (опционально) для Spotify-ссылок

3. **При необходимости отредактируйте `config/bot_settings.yaml`:**

    - ID каналов, таймауты, параметры Lavalink (search_limit, default_volume и т.д.)

!!! warning "Важно"
    Не добавляйте файлы `.env` и `data/bot_data.db` в Git.

## Запуск

### Продакшен (на VM)

```bash
docker compose up -d
```

Стартует три сервиса: `lavalink` (JVM-нода), `bot` (Python) и `watchtower` (авто-апдейт). Подробности — в [Деплое](deployment.md).

### Локальная разработка

Бот **не запускается локально**. Локально только тесты, линт и тайпчек:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest                          # тесты
ruff check . && ruff format .   # линт
mypy .                          # тайпчек
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
