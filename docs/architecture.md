# Архитектура PD Bot

## Общая структура проекта

```mermaid
graph TD
    A[main.py] --> B[Загрузка конфигурации]
    A --> C[Инициализация БД]
    A --> D[Загрузка когов]
    A --> E[Запуск бота]

    D --> F[Cogs]
    F --> F1[admin.py]
    F --> F2[activity.py]
    F --> F3[anime.py]
    F --> F4[fun.py - quote, deathbattle, snipe, etc.]
    F --> F6[lastmatch.py]
    F --> F7[links.py]
    F --> F8[logging_cog.py]
    F --> F9[music.py]
    F --> F10[role_reaction.py]
    F --> F11[twitch.py]
    F --> F12[top_reactions.py]

    D --> G[Handlers]
    G --> G1[events.py]
    G --> G2[message_handler.py]

    B --> H[config.py]
    C --> I[database.py]
```

## Поток данных в музыкальном модуле

Музыка работает поверх **Lavalink v4** (отдельный JVM-контейнер) и Python-клиента **wavelink 3.x**. Бот ничего не транскодирует сам — он лишь отправляет команды Lavalink-ноде и слушает её события.

```mermaid
sequenceDiagram
    participant User
    participant MusicCog
    participant Wavelink as wavelink (Python)
    participant Lavalink as Lavalink v4 (JVM)
    participant YT as YouTube / Spotify / ...

    User->>MusicCog: /play <запрос>
    MusicCog->>MusicCog: _ensure_player() — connect to VC если нужно
    MusicCog->>Wavelink: Playable.search(query)
    Wavelink->>Lavalink: GET /v4/loadtracks?identifier=ytmsearch:...
    Lavalink->>YT: запрос через youtube-source / LavaSrc
    YT-->>Lavalink: метаданные треков
    Lavalink-->>Wavelink: Search (list[Playable] или Playlist)
    Wavelink-->>MusicCog: результаты

    alt URL — единственный трек
        MusicCog->>Wavelink: player.queue.put(track)
        MusicCog->>Wavelink: player.play(...)
    else Текстовый поиск
        MusicCog->>User: SearchView с топ-N результатами
        User->>MusicCog: выбор трека
        MusicCog->>Wavelink: queue.put(track) + play()
    end

    Wavelink->>Lavalink: POST /v4/sessions/.../players/.../play
    Lavalink->>YT: получает поток (opus)
    Lavalink->>Discord: отправляет аудио через Voice Gateway

    Lavalink-->>Wavelink: TrackStartEvent
    Wavelink-->>MusicCog: on_wavelink_track_start
    MusicCog->>User: сообщение "Сейчас играет" + PlayerControlView
```

Ключевые компоненты:

- `cogs/music.py` — все hybrid-команды + слушатели событий wavelink.
- `utils/music/player.py::MusicPlayer` — subclass `wavelink.Player`; добавляет `text_channel`, `now_playing_message` и привязку «трек → заказчик» через `track.extras.requester_id`.
- `utils/music/ui.py` — три View: `PlayerControlView` (кнопки под now-playing), `SearchView` (Select), `QueueView` (пагинация).
- `utils/music/embeds.py` — единый стиль эмбедов: now-playing, added-to-queue, queue, playlist.
- `lavalink/application.yml` — конфиг JVM-сервиса с плагинами `youtube-source` и `LavaSrc`.

## Поток данных в модуле отслеживания активности

```mermaid
sequenceDiagram
    participant User
    participant Discord
    participant ActivityTracker
    participant ActivityDataManager
    participant Database

    User->>Discord: Изменение статуса игры
    Discord->>ActivityTracker: on_presence_update
    ActivityTracker->>ActivityTracker: Обновить текущие сессии

    Note over ActivityTracker: Периодическое сохранение (periodic_save)
    ActivityTracker->>ActivityDataManager: save_activity_data
    ActivityDataManager->>Database: Запись в daily_activity

    Note over ActivityTracker: Ежедневный отчет (00:00 МСК)
    ActivityTracker->>ActivityDataManager: generate_daily_report
    ActivityDataManager->>Database: Запрос данных за вчера
    Database-->>ActivityDataManager: Данные активности
    ActivityDataManager->>Discord: Отправить отчет
    ActivityDataManager->>Database: Перенос daily -> monthly

    Note over ActivityTracker: Ежемесячный отчет (1-е число, 12:00 МСК)
    ActivityTracker->>ActivityDataManager: generate_monthly_report
    ActivityDataManager->>Database: Запрос данных за месяц
    Database-->>ActivityDataManager: Данные активности
    ActivityDataManager->>Discord: Отправить отчет
```

## Поток данных в аниме-модуле

```mermaid
sequenceDiagram
    participant Scheduler
    participant AnimeCog
    participant SafebooruAPI
    participant Database
    participant Discord

    Note over Scheduler: Утренняя/вечерняя публикация
    Scheduler->>AnimeCog: morning_post() / evening_post()
    AnimeCog->>AnimeCog: _load_cache_from_db()
    AnimeCog->>Database: load_anime_cache(cache_size)
    Database-->>AnimeCog: Список ID постов

    AnimeCog->>SafebooruAPI: get_anime_image()
    SafebooruAPI-->>AnimeCog: URL изображения + post_id

    AnimeCog->>AnimeCog: Проверка post_id в кеше
    alt ID не в кеше
        AnimeCog->>Discord: Отправить изображение
        AnimeCog->>Database: save_anime_cache_item(post_id)
        AnimeCog->>AnimeCog: Добавить в кеш памяти
    else ID в кеше
        AnimeCog->>SafebooruAPI: Повторный запрос
    end
```

## Поток данных в модуле Quote

```mermaid
sequenceDiagram
    participant User
    participant FunCog
    participant QuotesUtils
    participant FileSystem
    participant Discord

    Note over User: Команда /quote без параметра
    User->>FunCog: /quote
    FunCog->>QuotesUtils: scan_quotes_folders()
    QuotesUtils->>FileSystem: Сканирование assets/quotes/
    FileSystem-->>QuotesUtils: Список пользователей с цитатами
    QuotesUtils-->>FunCog: Доступные пользователи
    FunCog->>FunCog: random.choice() - выбор случайного пользователя
    FunCog->>QuotesUtils: send_random_quote_image(user, embed=False)
    QuotesUtils->>FileSystem: Получение случайной цитаты
    FileSystem-->>QuotesUtils: Файл изображения
    QuotesUtils->>Discord: Отправка только файла (без embed)
    Discord-->>User: Показ случайной цитаты

    Note over User: Команда /quote с параметром
    User->>FunCog: /quote username
    FunCog->>QuotesUtils: validate_folder_exists(username)
    QuotesUtils->>FileSystem: Проверка пользователя
    FileSystem-->>QuotesUtils: Результат проверки
    alt Пользователь существует
        FunCog->>QuotesUtils: send_random_quote_image(username, embed=False)
        QuotesUtils->>QuotesUtils: get_random_image_from_folder()
        QuotesUtils->>FileSystem: Получение случайной цитаты
        FileSystem-->>QuotesUtils: Файл изображения
        QuotesUtils->>Discord: Отправка только файла (без embed)
        Discord-->>User: Показ цитаты пользователя
    else Пользователь не найден
        FunCog->>Discord: Отправка сообщения об ошибке
        Discord-->>User: "Цитаты пользователя не найдены"
    end
```

## Поток данных в модуле Dota 2

```mermaid
sequenceDiagram
    participant User
    participant LastMatchCog
    participant DotaAPI
    participant LinksDataManager
    participant Database

    User->>LastMatchCog: /lastmatch [member]
    LastMatchCog->>LinksDataManager: get_steam_ids(member)
    LinksDataManager->>Database: Запрос привязок
    Database-->>LinksDataManager: Steam IDs
    LinksDataManager-->>LastMatchCog: Steam IDs

    LastMatchCog->>DotaAPI: get_last_match(steam_ids)
    DotaAPI-->>LastMatchCog: Данные матча
    LastMatchCog->>User: Отправить информацию о матче
```

## Структура базы данных

```mermaid
erDiagram
    links {
        int discord_user_id
        int steam_id
    }

    daily_activity {
        int discord_user_id
        string game_name
        string date
        int seconds_played_today
    }

    monthly_activity {
        int discord_user_id
        string game_name
        int year
        int month
        int total_seconds_in_month
    }

    role_reactions {
        int guild_id
        int channel_id
        int message_id
        string emoji
        int role_id
        string description
    }

    twitch_streamers {
        int guild_id
        int channel_id
        string twitch_username
        string twitch_id
        bool is_live
        string last_stream_id
        int last_notification_time
    }

    anime_cache {
        int post_id PK
        int added_at
    }

    api_cache {
        string key PK
        json data
        float timestamp
        int ttl
    }

    reacted_messages {
        int message_id PK
        int channel_id
        int author_id
        text content
        text jump_url
        datetime posted_at
        int historical_reaction_count
        bool is_deleted
    }

    message_reactors {
        int id PK
        int message_id
        int user_id
        text emoji
        datetime reacted_at
    }

    links ||--o{ daily_activity : "tracks"
    daily_activity ||--o{ monthly_activity : "aggregates to"
    reacted_messages ||--o{ message_reactors : "uniqueReactors"
```

## Взаимодействие компонентов системы

```mermaid
graph TD
    A[main.py] --> B[Cogs]
    A --> C[Handlers]
    A --> D[Utils]

    B --> B1[admin.py]
    B --> B2[activity.py]
    B --> B3[anime.py]
    B --> B4[fun.py]
    B --> B6[lastmatch.py]
    B --> B7[links.py]
    B --> B8[logging_cog.py]
    B --> B9[music.py]
    B --> B10[role_reaction.py]
    B --> B11[twitch.py]
    B --> B12[top_reactions.py]

    C --> C1[events.py]
    C --> C2[message_handler.py]

    D --> D1[database.py]
    D --> D2[error_handler.py]
    D --> D3[logging_utils.py]
    D --> D4[activity_data_manager.py]
    D --> D5[dota_api.py]
    D --> D6[music/]
    D --> D8[models.py]

    D6 --> D6_1[player.py - MusicPlayer/setup_node]
    D6 --> D6_2[ui.py - Views]
    D6 --> D6_3[embeds.py]
    D6 --> D6_4[config.py - logger/colors]

    B2 --> D4
    B6 --> D5
    B9 --> D6
    B9 --> WL[wavelink 3.x]
    WL --> LL[Lavalink v4 - JVM]
    LL --> G[YouTube / Spotify / SoundCloud / ...]

    B1 --> D2
    B2 --> D2
    B3 --> D2
    B4 --> D2
    B6 --> D2
    B7 --> D2
    B9 --> D2
    B10 --> D2
    B11 --> D2
    B12 --> D2

    D1 --> E[SQLite DB - Tortoise ORM]
    D8 --> E
    D5 --> F[Stratz API]

    D --> D7[quotes_utils.py]
    B4 --> D7
```

## Жизненный цикл команды

```mermaid
sequenceDiagram
    participant User
    participant Discord
    participant Bot
    participant CommandHandler
    participant Cog
    participant ErrorHandler

    User->>Discord: Отправка команды
    Discord->>Bot: on_message / on_interaction
    Bot->>CommandHandler: Парсинг и поиск команды
    CommandHandler->>Cog: Вызов метода команды

    alt Успешное выполнение
        Cog->>User: Ответ на команду
    else Ошибка
        Cog->>ErrorHandler: Перехват исключения
        ErrorHandler->>User: Сообщение об ошибке
    end
```

## Система логирования

```mermaid
graph TD
    A[main.py] --> B[setup_logging]
    B --> C[Файл логов]
    B --> D[Консоль]

    E[Модули] --> F[Логгеры]
    F --> G[Иерархия логгеров]

    G --> H[bot.main]
    G --> I[bot.cogs.*]
    G --> J[bot.utils.*]
    G --> K[bot.handlers.*]

    I --> I1[bot.cogs.music]
    I --> I2[bot.cogs.activity]
    I --> I3[bot.cogs.logging_cog]

    J --> J1[bot.utils.dota_api]
    J --> J2[bot.utils.music.*]

    J2 --> J2_1[bot.utils.music.player]
    J2 --> J2_2[bot.utils.music.ui]
    J2 --> J2_3[bot.utils.music.config]
    J2 --> J2_4[bot.utils.music.embeds]

    C --> L[LoggingCog]
    L --> M[Discord канал]
```

### Особенности системы логирования

- **Иерархическая структура**: Все логгеры следуют единой иерархии, начиная с `bot`
- **JSON-форматирование**: Логи сохраняются в JSON-формате для удобного анализа
- **Цветной вывод в консоль**: Разные уровни логирования отображаются разными цветами
- **Пересылка в Discord**: Логи автоматически пересылаются в указанный Discord-канал
- **Контекстное логирование**: Возможность добавления контекста к группе логов
