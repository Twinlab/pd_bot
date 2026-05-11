# PD Bot

Многофункциональный Discord бот на Python с использованием discord.py.

## Возможности

- Интеграция с Dota 2 API (Stratz GraphQL) для статистики матчей
- Музыкальный плеер на базе **Lavalink v4 + wavelink 3.x** (YouTube/Spotify/SoundCloud/Apple Music/Deezer/Bandcamp, обход YouTube bot-detection через OAuth)
- Отслеживание игровой активности с отчётами
- Twitch уведомления о стримах
- Автопостинг аниме-артов
- Система ролей по реакциям
- Лидерборд сообщений по числу уникальных реакций
- Развлекательные команды

## Быстрый старт

```bash
cp .env.example .env
# Заполнить BOT_TOKEN в .env
docker compose up -d --build
```

## Разработка

```bash
# Установка зависимостей
.venv/bin/pip install -e ".[dev]"

# Запуск
.venv/bin/python main.py

# Тесты
pytest

# Линтинг
ruff check . && ruff format .
```

## Документация

Подробная документация доступна на [сайте проекта](https://twinlab.github.io/pd_bot/):

- [Начало работы](https://twinlab.github.io/pd_bot/getting-started/)
- [Архитектура](https://twinlab.github.io/pd_bot/architecture/)
- [Команды](https://twinlab.github.io/pd_bot/commands/)
- [Деплой](https://twinlab.github.io/pd_bot/deployment/)
- [Стиль кода](https://twinlab.github.io/pd_bot/style-guide/)

Также доступна локально в директории `docs/`.

## Лицензия

MIT
