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
    F --> F8[logging_cog.py]
    F --> F9[music.py]
    F --> F10[role_reaction.py]
    F --> F11[twitch.py]
    F --> F12[top_reactions.py]
    F --> F13[user_stats.py]
    F --> F14[profile.py]
    F --> F15[party.py]
    F --> F16[help.py]

    D --> G[Handlers]
    G --> G1[events.py]
    G --> G2[message_handler.py]

    B --> H[config.py]
    C --> I[database.py]
```

### Жизненный цикл запуска

`main()` инициализирует БД и загружает коги/хендлеры **до** `bot.start()`, поэтому
к моменту `MyBot.setup_hook` дерево app-команд уже заполнено. Синхронизация
slash-команд (и контекст-меню) делается один раз за процесс именно в
`setup_hook` — это канон discord.py и заменяет прежний ручной флаг в
`Events.on_ready` (тот срабатывал на каждый reconnect). `on_ready` теперь только
логирует готовность и ставит presence. Persistent-вью регистрируются в `cog_load`
своих когов.

Контекст-меню (ПКМ) живут внутри когов: создаются как `app_commands.ContextMenu`
в `__init__` и добавляются в `bot.tree`, снимаются в `cog_unload`. Активно одно —
«Профиль» (по юзеру, `cogs/profile.py`). «В цитаты» (по сообщению,
`cogs/fun.py`) заморожено: колбэк/хелпер есть, но в дерево не регистрируются —
ждём доработки до «скриншот-цитаты».

`/help` не хранит отдельный список команд: `HelpCog` читает актуальный
`CommandTree` и группирует slash-команды вместе с контекстными действиями по
подсистемам. Это не даёт справке расходиться с реально синхронизированным деревом.

### Завершение процесса

`main()` устанавливает обработчики `SIGINT` и `SIGTERM`. Они отменяют основную
задачу и переводят процесс в общий `finally`: Discord-клиент получает до 3 секунд,
HTTP/Lavalink-клиенты закрываются параллельно с лимитом 2 секунды каждый, после
чего БД закрывается отдельным шагом с лимитом 2 секунды. Зависание одного сетевого
ресурса поэтому не мешает закрыть остальные ресурсы и SQLite.

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
        MusicCog->>User: SearchLayoutView с топ-N результатами
        User->>MusicCog: выбор трека
        MusicCog->>Wavelink: queue.put(track) + play()
    end

    Wavelink->>Lavalink: POST /v4/sessions/.../players/.../play
    Lavalink->>YT: получает поток (opus)
    Lavalink->>Discord: отправляет аудио через Voice Gateway

    Lavalink-->>Wavelink: TrackStartEvent
    Wavelink-->>MusicCog: on_wavelink_track_start
    MusicCog->>User: NowPlayingView — CV2-карточка «Сейчас играет»
```

Ключевые компоненты:

- `cogs/music.py` — все hybrid-команды + слушатели событий wavelink.
- `utils/music/player.py::MusicPlayer` — subclass `wavelink.Player`; добавляет `text_channel`, `now_playing_message` и привязку «трек → заказчик» через `track.extras.requester_id`.
- `utils/music/ui.py` — Components V2-представления `NowPlayingView`, `SearchLayoutView` и `QueueLayoutView`: контент и интерактив живут в одном `LayoutView` (контейнер + `Section`/`Thumbnail` + `ActionRow`-кнопки). Для `/nowplaying` используется статический `now_playing_static_view`.
- `utils/music/embeds.py` — общие форматтеры и CV2-карточки `status_card`, `added_to_queue_card`, `added_playlist_card`.
- `lavalink/application.yml` — конфиг JVM-сервиса с плагинами `youtube-source` и `LavaSrc`.

Выбор трека и кнопки паузы, пропуска и остановки подтверждают interaction через
`defer()` до сетевого вызова Lavalink. После выполнения действия карточка
обновляется через `edit_original_response()`, чтобы задержка ноды не приводила
к просроченному первому ответу Discord.

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

Завершённые интервалы игровых сессий хранятся отдельно от текущих сессий в
`ActivityTracker._pending_activity`, с разбивкой по московским датам. Выход из
игры или смена игры сразу закрывает старую сессию в памяти. При ошибке БД
следующее сохранение повторяет запись фиксированного числа секунд, даже если
активных сессий уже нет. Успешно записанные даты удаляются из очереди отдельно,
поэтому частичный сбой на границе суток не удваивает уже сохранённое время.
Очередь находится в памяти процесса и не переживает аварийный перезапуск.

## Поток данных в аниме-модуле

```mermaid
sequenceDiagram
    participant Scheduler
    participant AnimeCog
    participant DanbooruAPI
    participant Database
    participant Discord

    Note over Scheduler: Утренняя/вечерняя публикация
    Scheduler->>AnimeCog: morning_post() / evening_post()
    AnimeCog->>AnimeCog: _load_cache_from_db()
    AnimeCog->>Database: load_anime_cache(cache_size)
    Database-->>AnimeCog: Список ID постов

    AnimeCog->>DanbooruAPI: get_anime_image(rating, tag)
    DanbooruAPI-->>AnimeCog: Список постов (url, score, метаданные)
    AnimeCog->>AnimeCog: Фильтр по score / рейтингу / excluded_tags

    AnimeCog->>AnimeCog: Выбор поста, которого нет в кеше
    alt Найден свежий пост
        AnimeCog->>Discord: Отправить карточку с изображением
        AnimeCog->>AnimeCog: Добавить в кеш памяти
        AnimeCog->>Database: AnimeCache.create(post_id)
    else Все в кеше / пусто
        AnimeCog->>DanbooruAPI: Повторный запрос / fallback
    end
```

Ручная и плановая публикация используют общий `asyncio.Lock` на весь цикл
выбора, отправки и обновления кеша. Следующая публикация выбирает изображение
с учётом результата предыдущей. Если Discord отклонил отправку, изображение
не попадает в кеш и остаётся доступным для повторной попытки.

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

## Привязки в профиле

`cogs/profile.py` открывает публичный `/profile` и личный профиль через ПКМ,
владеет `ProfileAccountService`. Публичные вкладки могут переключать все участники;
управление привязками разрешено только владельцу и использует личные диалоги.
`utils/profile/account_views.py` отвечает за форму с одним полем, предпросмотр,
выбор аккаунта и подтверждение отвязки. На каждом этапе проверяются владелец
и срок действия исходной панели. HTTP-сессия Steam закрывается при выгрузке кога.

`utils/profile/accounts.py` разбирает только известные форматы Steam, Dota и FACEIT.
Числовые Steam ID преобразуются локально, именные ссылки разрешаются через
`ResolveVanityURL` с необязательным `STEAM_API_KEY`; FACEIT использует существующий API-клиент.
Имена Dota кэшируются в `APICache`; открытие вкладки не вызывает внешние API.

`ProfileAccountsDataManager` записывает в существующие `links` и `cs_links`.
Проверки лимита, дубликата и добавление выполняются в транзакции под блокировкой
пользователя, общей для всех панелей процесса. Для отвязки обязательно задаются
владелец и конкретный аккаунт. Модели и схема базы не меняются.

## Объявления об обновлениях

`cogs/announcements.py` запускает доставку после `on_ready` только в production.
Повторный `on_ready` не создаёт вторую задачу. Текст и стабильный ID релиза берутся
из `config/release_notes.yaml`, а канал — из `channels.announcements`.
Пустой текст отключает публикацию; новая ревизия образа сама по себе анонс не создаёт.

`utils/release_announcements.py` сохраняет журнал всех объявленных ID в
`data/release_announcements.json` на существующем Docker volume. Перед отправкой
атомарно записывается намерение, после отправки — ID сообщения. Если подтверждение
потерялось, бот ищет собственную CV2-карточку с подписью релиза в истории канала
после начала попытки. Ошибка чтения истории или повреждённый журнал запрещают
повторную отправку вслепую. Повторы после ошибок выполняются раз в пять минут.
Сохранённые ID предотвращают повтор при откате на уже объявленный релиз.
Схема SQLite не меняется. Новых команд или persistent-кнопок у объявления нет.

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

    daily_user_stats {
        int discord_user_id
        string date
        int messages
        int voice_seconds
    }

    monthly_user_stats {
        int discord_user_id
        int year
        int month
        int messages
        int voice_seconds
    }

    links ||--o{ daily_activity : "tracks"
    daily_activity ||--o{ monthly_activity : "aggregates to"
    daily_user_stats ||--o{ monthly_user_stats : "aggregates to"
    reacted_messages ||--o{ message_reactors : "uniqueReactors"
```

Таблицы `daily_user_stats` / `monthly_user_stats` ведёт `cogs/user_stats.py`
(сообщения + «умное» голосовое время), а `wrapped/`-подсистема собирает из них,
из игровой активности и из реакций красивые wrapped-сводки (matplotlib).

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
    B --> B8[logging_cog.py]
    B --> B9[music.py]
    B --> B10[role_reaction.py]
    B --> B11[twitch.py]
    B --> B12[top_reactions.py]
    B --> B13[user_stats.py]

    C --> C1[events.py]
    C --> C2[message_handler.py]

    D --> D1[database.py]
    D --> D2[error_handler.py]
    D --> D3[logging_utils.py]
    D --> D4[activity_data_manager.py]
    D --> D5[dota_api.py]
    D --> D6[music/]
    D --> D8[models.py]
    D --> D9[user_stats_data_manager.py]
    D --> D10[wrapped/ - voice, builder, render]
    D --> D11[match_card/ - PNG-карточки матчей Pillow]

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
- **Граница запуска**: Каждый новый процесс начинает Discord-tail отдельным заголовком
  со временем и окружением; `WARNING`/`ERROR`/`CRITICAL` получают заметный префикс
- **Без рекурсивного шума**: Служебные `INFO`/`DEBUG` самого `LoggingCog` не идут
  обратно в Discord, но полностью сохраняются в файловом JSON-логе
- **Контекстное логирование**: Возможность добавления контекста к группе логов
