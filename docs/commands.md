# Команды

## Административные (`cogs/admin.py`)

| Команда | Описание |
|---------|----------|
| `/clear [count] [user]` | Удаление сообщений (до 100, обходит 14-дневный лимит) |
| `/kick <member> [reason]` | Исключение пользователя с сервера |
| `/restart` | (Владелец) Перезапуск бота |

## Отслеживание активности (`cogs/activity.py`)

| Команда | Описание |
|---------|----------|
| `/activity [test_mode]` | (Админ) Текущая дневная статистика с пагинацией |
| `/mystats [user] [month] [year]` | Статистика пользователя за месяц |
| `/mystatsall [user]` | Статистика пользователя за всё время |
| `/report_daily <year> <month> <day>` | (Админ) Ручной ежедневный отчёт |
| `/report_monthly <year> <month>` | (Админ) Ручной ежемесячный отчёт |

**Автоматические отчёты:**

- Ежедневный отчёт (за вчера) — 00:00 МСК
- Ежемесячный отчёт (за прошлый месяц) — 1-го числа в 12:00 МСК

## Аниме (`cogs/anime.py`)

| Команда | Описание |
|---------|----------|
| `/post_anime` | (Админ) Ручная публикация аниме-изображения |

Автоматическая публикация дважды в день (10:00 и 18:00 UTC) из safebooru.org.

Настройка тегов в `config/bot_settings.yaml`:

```yaml
anime:
  tags: ["anime", "1girl", "cute"]
  excluded_tags: ["nude", "nsfw"]
  rating: "safe"
```

## Развлечения (`cogs/fun.py`)

| Команда | Описание |
|---------|----------|
| `/deathbattle [member1] [member2]` | Симуляция битвы |
| `/snipe` | Последнее удалённое сообщение в канале |
| `/penis [user]` | Измерение "пениса" |
| `/avatar [user]` | Аватар пользователя |
| `/quote [user]` | Случайная цитата пользователя |

### Команда Quote

Цитаты хранятся как изображения в `assets/quotes/<username>/`. Добавление:

1. Создайте папку в `assets/quotes/` с именем пользователя
2. Добавьте изображения (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`)
3. Пользователь автоматически появится в автокомплите

## Dota 2 (`cogs/lastmatch.py`, `cogs/links.py`)

| Команда | Описание |
|---------|----------|
| `/link <player_id>` | Привязка Steam ID (до 5 аккаунтов) |
| `/unlink [player_id]` | Отвязка Steam ID |
| `/links` | Список привязанных аккаунтов |
| `/lastmatch [member]` | Информация о последнем матче |

## Музыка (`cogs/music.py`)

Базируется на **Lavalink v4** (отдельный JVM-контейнер) и Python-клиенте **wavelink 3.x**. Подробности развёртывания см. в [Деплое](deployment.md).

| Команда | Описание |
|---------|----------|
| `/play <query>` | URL (YouTube/Spotify/Apple Music/SoundCloud/Bandcamp/Twitch/Vimeo) или текстовый поиск (по умолчанию через YouTube Music) |
| `/skip` | Пропустить текущий трек (заказчик трека или админ) |
| `/stop` | Остановить и покинуть канал (только админ) |
| `/pause` | Пауза |
| `/resume` | Возобновить |
| `/queue [page]` (`/q`) | Постраничная очередь с кнопками `◀ 🔄 ▶` |
| `/nowplaying` (`/np`) | Текущий трек с обложкой и метаданными |
| `/remove <index>` | Удалить трек из очереди (заказчик или админ) |
| `/clear` | Очистить очередь (только админ) |
| `/loop <off\|track\|queue>` | Режим повтора |
| `/shuffle` | Перемешать очередь |
| `/volume <0-200>` | Громкость (только админ) |
| `/seek <MM:SS\|HH:MM:SS\|секунды>` | Перемотать текущий трек |

Все команды — гибридные: работают и как `/slash`, и с префиксом `!`.

Сообщение "Сейчас играет" содержит кнопки управления (▶/⏸, ⏭, ⏹, 🔁, 🔀, 📜). Бот автоматически покидает канал, если остаётся один или простаивает без музыки (`music.voice.inactive_timeout` секунд).

### Поддерживаемые источники

| Источник | Через | Заметки |
|----------|-------|---------|
| YouTube / YouTube Music | `youtube-source` плагин Lavalink | OAuth с burner-аккаунтом для обхода bot-detection (см. деплой) |
| Spotify | LavaSrc плагин | Метаданные через Spotify API → стрим через YouTube. Требует `SPOTIFY_CLIENT_ID/SECRET` |
| Apple Music, Deezer, Yandex Music | LavaSrc плагин | По умолчанию выключены в `lavalink/application.yml` — включить при необходимости |
| SoundCloud, Bandcamp, Twitch, Vimeo, Nico | стандартные source-ы Lavalink | Работают «из коробки» |

### Поиск по тексту

`/play Imagine Dragons Believer` → wavelink делает `ytmsearch:` запрос, возвращает топ-10. Бот показывает Select-меню — выбираете нужный трек, он встаёт в очередь.

Альтернативные префиксы (продвинутое использование, можно передать в `/play`):

- `spsearch:queen bohemian` — поиск в Spotify
- `scsearch:queen bohemian` — поиск в SoundCloud
- `ytsearch:queen bohemian` — обычный YouTube (по умолчанию используется YouTube Music)

### Права доступа

- **Админ сервера**: всё.
- **Заказчик текущего трека**: pause/resume/skip/loop/shuffle/seek/remove (только свои треки).
- **Прочие в том же VC**: nowplaying, queue.
- **Не в VC**: ничего, кроме просмотра nowplaying/queue.

### Настройка

```yaml
music:
  lavalink:
    secure: false              # https/wss для удалённой ноды за TLS-прокси
    identifier: "MAIN"
    search_limit: 10           # сколько результатов в Select-меню
    default_volume: 50         # стартовая громкость
    max_volume: 200            # верхняя граница /volume
    queue_page_size: 10        # треков на странице /queue
  voice:
    connection_timeout: 30.0
    inactive_timeout: 300      # сек простоя до автодисконнекта
```

Host/port/password Lavalink-ноды берутся из `.env`: `LAVALINK_HOST`, `LAVALINK_PORT`, `LAVALINK_SERVER_PASSWORD`.

## Twitch (`cogs/twitch.py`)

| Команда | Описание |
|---------|----------|
| `/twitch_add <username> [channel]` | (Админ) Добавить стримера для отслеживания |
| `/twitch_remove <username>` | (Админ) Удалить стримера |
| `/twitch_list` | Список отслеживаемых стримеров |

Требуется `TWITCH_CLIENT_ID` и `TWITCH_CLIENT_SECRET` в `.env`.

## Роли по реакциям (`cogs/role_reaction.py`)

| Команда | Описание |
|---------|----------|
| `/setup_role_message` | (Админ) Создать сообщение для ролей |
| `/role_assign <role> <emoji> <description>` | (Админ) Добавить роль |
| `/role_remove <emoji>` | (Админ) Удалить роль |

## Топ реакций (`cogs/top_reactions.py`)

| Команда | Описание |
|---------|----------|
| `/topreactions [period]` | (Админ, тест-режим) Топ сообщений по уникальным реакторам (`month` / `year` / `all`) |

Команда сейчас в тест-режиме и доступна только администраторам сервера — пока
обкатываем live-трекинг и обработку исторических данных. После стабилизации
ограничение будет снято.

Бот слушает события `on_raw_reaction_*` и поддерживает в БД таблицы:

- `reacted_messages` — метаданные сообщений с реакциями
- `message_reactors` — записи `(message_id, user_id, emoji)` для подсчёта уникальных реакторов

При первой реакции на ранее неизвестное боту сообщение выполняется ленивая
подгрузка: бот фетчит сообщение и все его реакции, чтобы счётчик отражал
реальное состояние. Это позволяет корректно работать со старыми сообщениями,
на которые ставят реакции через лидерборд.

### Настройка

```yaml
top_reactions:
  live_top: 10               # Сколько позиций показывать в month / year
  all_time_top: 50           # Сколько позиций показывать в all
  per_page: 10               # Позиций на одной странице
  content_preview_length: 200
  view_timeout: 300
```
