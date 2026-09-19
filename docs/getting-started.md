# Начало работы

PD Bot рассчитан на один Discord-сервер. Для своего экземпляра нужны отдельное приложение Discord, Docker с Compose v2 и копия репозитория. Команды ниже предназначены для Linux и выполняются из корня проекта. Python на хосте нужен только для разработки; контейнер уже содержит Python 3.13.

## 1. Создайте приложение Discord

В [Developer Portal](https://discord.com/developers/applications) создайте приложение и получите токен бота. На странице **Bot → Privileged Gateway Intents** включите **Presence Intent**, **Server Members Intent** и **Message Content Intent**: код использует все три для активности, участников и текстовых команд. Описание разрешений есть в [документации Discord](https://docs.discord.com/developers/events/gateway#privileged-intents).

Установите приложение на свой сервер со scopes `bot` и `applications.commands` через ссылку установки приложения. Это [серверная установка бота](https://docs.discord.com/developers/topics/oauth2#bot-authorization-flow).

Выдайте права для используемых функций:

| Функции | Права бота |
| --- | --- |
| Команды, карточки и статистика | View Channels, Send Messages, Embed Links, Attach Files, Read Message History |
| Музыка | Connect и Speak в нужных голосовых каналах |
| Кнопки ролей | Manage Roles; роль бота выше выдаваемых ролей |
| Модерация | Manage Messages для `/clear`, Kick Members для `/kick` |

Доступ пользователей к административным командам проверяется отдельно. Канал логов лучше сделать доступным только администраторам.

## 2. Заполните настройки

Скопируйте пример окружения и отредактируйте его:

```bash
cp .env.example .env
chmod 600 .env
```

Для запуска через Compose задайте:

- `BOT_TOKEN` — токен созданного приложения.
- `GUILD_ID` — ID вашего единственного сервера. С ним команды регистрируются именно на этом сервере.
- `LAVALINK_SERVER_PASSWORD` — длинный случайный пароль, одинаковый для бота и Lavalink; например, результат `openssl rand -hex 32`.

Внутри Docker оставьте `LAVALINK_HOST=lavalink` и `LAVALINK_PORT=2333`. `localhost` внутри контейнера бота указывает на сам бот, а не на музыкальную ноду.

Остальные ключи нужны соответствующим интеграциям. Ненужные примерные значения удалите или оставьте пустыми.

| Переменные | Для чего нужны |
| --- | --- |
| `STRATZ_API_KEY` | Статистика Dota 2 |
| `FACEIT_API_KEY` | Профили и матчи FACEIT / CS2 |
| `STEAM_API_KEY` | Разрешение именных Steam-ссылок и получение публичных данных профиля |
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Уведомления Twitch |
| `DANBOORU_LOGIN`, `DANBOORU_API_KEY` | Авторизованные запросы аниме-модуля; без них используется анонимный доступ |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | Распознавание Spotify-ссылок в Lavalink |
| `YOUTUBE_REFRESH_TOKEN` | OAuth YouTube; первый вход описан ниже |

В `config/bot_settings.yaml` **замените все ID каналов и пользователей своими**. Настройте публикации, расписания, игровые роли и персональные реакции; удалите ненужные персональные реакции из примера. Для аниме-модуля `channels.anime: 0` отключает планировщик публикаций. Секреты храните в `.env`, не в YAML или Git.

Перед первым запуском в разделе `channels` установите `announcements: null`. Это отключает автоматический анонс из поставляемого `config/release_notes.yaml`. Включайте канал объявлений только после подготовки собственного текста релиза; подробности есть в [эксплуатации](deployment.md#release-announcements).

## 3. Соберите свой экземпляр

Базовый `docker-compose.yml` использует готовый образ проекта. Чтобы ваш экземпляр содержал текущий код и настройки, создайте рядом файл `compose.selfhost.yaml`:

```yaml
services:
  bot:
    build: .
    image: pd-bot-local:latest
    pull_policy: never
    volumes:
      - ./config/bot_settings.yaml:/app/config/bot_settings.yaml:ro
    labels:
      com.centurylinklabs.watchtower.enable: "false"
```

Этот файл применяется явно через `-f`; остальные тома и зависимости берутся из основного Compose. Правила объединения описаны в [Docker Compose](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/). Сохраните локальные настройки отдельно от публичных коммитов.

Для новой установки подготовьте каталоги с правами пользователей контейнеров. Бот работает с UID 1000; используемый Alpine-образ Lavalink — с UID/GID 322, согласно [документации образа](https://lavalink.dev/getting-started/docker).

```bash
mkdir -p data logs lavalink/plugins lavalink/logs
sudo chown -R 1000:1000 data logs
sudo chown -R 322:322 lavalink/plugins lavalink/logs

docker compose -f docker-compose.yml -f compose.selfhost.yaml config --quiet
docker compose -f docker-compose.yml -f compose.selfhost.yaml build bot
docker compose -f docker-compose.yml -f compose.selfhost.yaml up -d lavalink
```

Последняя команда запускает Lavalink и его зависимость `yt-cipher`. Сначала завершите OAuth YouTube, если ещё нет refresh token.

## 4. Настройте YouTube и запустите бота {#youtube-setup}

В текущем `lavalink/application.yml` включён OAuth. При пустом `YOUTUBE_REFRESH_TOKEN` плагин выводит в журнал адрес и код входа:

```bash
docker compose -f docker-compose.yml -f compose.selfhost.yaml logs -f lavalink
```

Откройте выданный адрес и завершите вход **отдельным Google-аккаунтом**. Полученный refresh token сохраните в `.env` как `YOUTUBE_REFRESH_TOKEN`. Не публикуйте этот журнал: он может содержать токен. Порядок входа описан в [youtube-source](https://github.com/lavalink-devs/youtube-source#using-oauth-tokens).

```bash
docker compose -f docker-compose.yml -f compose.selfhost.yaml up -d --force-recreate lavalink
docker compose -f docker-compose.yml -f compose.selfhost.yaml up -d bot
docker compose -f docker-compose.yml -f compose.selfhost.yaml ps
```

Watchtower этой последовательностью не запускается. Схема автоматического обновления описана в [эксплуатации](deployment.md#registry-updates).

Проверьте `/help`, `/profile`, одну игровую интеграцию с настроенным ключом и короткое воспроизведение `/play` в голосовом канале. Статус `healthy` у Lavalink проверяет доступность порта, поэтому звук стоит проверить отдельно. Если команда не появилась, проверьте `GUILD_ID`, установку приложения и сообщения о синхронизации в журнале бота.

## Разработка без запуска бота

Для тестов не нужны реальные токены или работающий Lavalink. Используйте отдельный клон без рабочего `.env`.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
mypy .
```

В PowerShell активация окружения: `.venv\Scripts\Activate.ps1`. Вместо полной проверки во время работы запускайте нужный файл тестов, например `pytest tests/test_cogs/test_music_cog.py`.

Dockerfile и CI устанавливают зависимости через `pip` из `pyproject.toml`. Наличие `uv.lock` в репозитории не означает, что он используется этими сборками.

Дальше: [команды](commands.md), [архитектура](architecture.md), [обновление и резервные копии](deployment.md).
