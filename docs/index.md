# PD Bot

Многофункциональный Discord бот, разработанный на Python с использованием библиотеки discord.py.

## Возможности

- **Dota 2 интеграция** — статистика матчей через Stratz GraphQL API
- **Музыкальный плеер** — Lavalink v4 + wavelink 3.x (YouTube, Spotify, Apple Music, SoundCloud, Bandcamp, Twitch — с OAuth-обходом YouTube bot-detection)
- **Отслеживание активности** — мониторинг игровой активности с ежедневными/ежемесячными отчётами
- **Twitch уведомления** — оповещения о начале стримов
- **Аниме-арты** — автопостинг SFW изображений с safebooru.org
- **Роли по реакциям** — автоматическая выдача ролей
- **Развлекательные команды** — deathbattle, snipe, quote и другие

Бот использует гибридные команды, поддерживающие как префиксный синтаксис (`!команда`), так и slash-команды (`/команда`).

## Быстрый старт

```bash
# Клонировать репозиторий
git clone https://github.com/twinlab/pd_bot.git
cd pd_bot

# Настроить окружение
cp .env.example .env
# Заполнить .env (BOT_TOKEN обязателен)

# Запустить через Docker
docker compose up -d --build
```

Подробнее — в разделе [Начало работы](getting-started.md).

## Технологии

| Компонент | Технология |
|-----------|-----------|
| Язык | Python 3.13+ |
| Discord API | discord.py |
| База данных | SQLite + Tortoise ORM |
| Конфигурация | Pydantic Settings + YAML |
| Музыка | Lavalink v4 + wavelink 3.x (плагины: youtube-source, LavaSrc) |
| Dota 2 API | Stratz GraphQL |
| CI/CD | GitHub Actions + Watchtower |
| Контейнеризация | Docker |
