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
    F --> F4[fun.py]
    F --> F5[giveaway.py]
    F --> F6[lastmatch.py]
    F --> F7[links.py]
    F --> F8[logging_cog.py]
    F --> F9[music.py]
    F --> F10[role_reaction.py]
    F --> F11[twitch.py]
    F --> F12[update.py]

    D --> G[Handlers]
    G --> G1[events.py]
    G --> G2[message_handler.py]

    B --> H[config.py]
    C --> I[database.py]
```

## Поток данных в музыкальном модуле

```mermaid
sequenceDiagram
    participant User
    participant MusicCog
    participant MusicPlayer
    participant YTIntegration

    User->>MusicCog: /play [query]
    MusicCog->>YTIntegration: search_youtube(query)
    YTIntegration-->>MusicCog: search_results
    MusicCog->>User: Показать результаты поиска
    User->>MusicCog: Выбрать трек
    MusicCog->>MusicPlayer: queue_track(url, user)
    MusicPlayer->>YTIntegration: download_track(url)
    YTIntegration-->>MusicPlayer: track_info
    MusicPlayer->>MusicPlayer: play_next()
    MusicPlayer->>User: Отправить "Сейчас играет"
```

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

    links ||--o{ daily_activity : "tracks"
    daily_activity ||--o{ monthly_activity : "aggregates to"
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
    B --> B5[giveaway.py]
    B --> B6[lastmatch.py]
    B --> B7[links.py]
    B --> B8[logging_cog.py]
    B --> B9[music.py]
    B --> B10[role_reaction.py]
    B --> B11[twitch.py]
    B --> B12[update.py]

    C --> C1[events.py]
    C --> C2[message_handler.py]

    D --> D1[database.py]
    D --> D2[error_handler.py]
    D --> D3[logging_utils.py]
    D --> D4[activity_data_manager.py]
    D --> D5[dota_api.py]
    D --> D6[music/]

    D6 --> D6_1[player.py]
    D6 --> D6_2[ui.py]
    D6 --> D6_3[embeds.py]
    D6 --> D6_4[yt_integration.py]

    B2 --> D4
    B6 --> D5
    B9 --> D6

    B1 --> D2
    B2 --> D2
    B3 --> D2
    B4 --> D2
    B5 --> D2
    B6 --> D2
    B7 --> D2
    B9 --> D2
    B10 --> D2
    B11 --> D2
    B12 --> D2

    D1 --> E[SQLite DB]
    D5 --> F[Stratz API]
    D6_4 --> G[YouTube API]
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
