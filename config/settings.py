"""Модели настроек бота на основе Pydantic."""

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    import discord


class Environment(StrEnum):
    """Окружения для запуска бота."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class ChannelConfig(BaseModel):
    """Конфигурация каналов Discord.

    Значения ID каналов всегда переопределяются в ``config/bot_settings.yaml``.
    Нулевые дефолты ниже — это «sentinel», который заставит код, наткнувшийся
    на неконфигурированный канал, явно упасть или залогировать ошибку,
    вместо того чтобы случайно слать в чужой канал по хардкодному ID.

    Attributes:
        logging: ID канала для логов бота.
        anime: ID канала для публикации аниме (опционально).
        twitch: ID канала для уведомлений Twitch.
        activity_reports: ID канала для отчетов активности.
        role_reactions_default: ID канала по умолчанию для ролей (опционально).
    """

    logging: int = 0
    anime: int | None = None
    twitch: int = 0
    activity_reports: int = 0
    role_reactions_default: int | None = None


class TimeoutConfig(BaseModel):
    """Конфигурация таймаутов и интервалов.

    Attributes:
        activity_min_record: Минимальное время записи активности (сек)
        activity_max_record: Максимальное время записи активности (сек)
        activity_monthly_min_time: Минимальное время для месячного отчета (сек)
        activity_periodic_save: Интервал периодического сохранения (сек)
        log_check_interval: Интервал проверки логов (сек)
        purge_rate_limit: Лимит частоты очистки сообщений (сек)
        giveaway_min_duration: Минимальная длительность розыгрыша (сек)
        giveaway_max_duration: Максимальная длительность розыгрыша (сек)
    """

    activity_min_record: int = 10
    activity_max_record: int = 172800
    activity_monthly_min_time: int = 1800
    activity_periodic_save: int = 300
    log_check_interval: int = 5
    purge_rate_limit: int = 10
    giveaway_min_duration: int = 10
    giveaway_max_duration: int = 604800
    admin_purge_threshold: int = 10
    admin_purge_delete_after: int = 5
    admin_restart_delay: float = 0.5
    old_message_delete_delay: float = 0.5
    update_restart_delay: int = 1


class LimitConfig(BaseModel):
    """Конфигурация лимитов и ограничений.

    Attributes:
        max_message_length: Максимальная длина сообщения
        purge_max_count: Максимальное количество сообщений для очистки
        purge_min_count: Минимальное количество сообщений для очистки
        links_max_per_user: Максимальное количество привязок на пользователя
        activity_items_per_page: Количество элементов на странице активности
    """

    max_message_length: int = 1990
    purge_max_count: int = 100
    purge_min_count: int = 1
    links_max_per_user: int = 5
    activity_items_per_page: int = 10
    giveaway_participants_chunk: int = 1900
    twitch_streamers_chunk: int = 900
    update_output_max_length: int = 1900
    logging_buffer_overhead: int = 10
    discord_api_days_limit: int = 14
    history_multiplier: int = 2


class ColorConfig(BaseModel):
    """Конфигурация цветов для эмбедов.

    Attributes:
        default: Цвет по умолчанию
        error: Цвет для ошибок
        success: Цвет для успешных операций
        info: Цвет для информационных сообщений
        warning: Цвет для предупреждений
        twitch: Цвет для Twitch уведомлений
    """

    default: str = "#0099ff"
    error: str = "#ff0000"
    success: str = "#00ff00"
    info: str = "#ffaa00"
    warning: str = "#ff8800"
    twitch: str = "#6441a4"


class AnimeScheduleConfig(BaseModel):
    """Конфигурация расписания публикации аниме.

    Attributes:
        morning_hour: Час утренней публикации (UTC)
        morning_minute: Минута утренней публикации (UTC)
        evening_hour: Час вечерней публикации (UTC)
        evening_minute: Минута вечерней публикации (UTC)
    """

    morning_hour: int = 10
    morning_minute: int = 0
    evening_hour: int = 18
    evening_minute: int = 0


class AnimeConfig(BaseModel):
    """Конфигурация аниме-модуля (источник изображений — Danbooru).

    Лимит Danbooru (Member) — 2 «обычных» тега на запрос; ``score:``/``rating:`` —
    бесплатные метатеги и не считаются, а ``order:`` считается. Отсюда две стратегии:

    - С франшизей: ``<франшиза> order:random rating:X score:>=N`` (истинный рандом),
      «девочка» гарантируется фильтром по тегам поста на стороне бота.
    - Только базовый тег: ``<1girl/2girls> order:rank rating:X`` (ранг = качество).

    Attributes:
        base_tags: Базовые теги; ровно один из них в КАЖДОМ запросе (гарантия девочки).
        extra_tags: Пул франшиз; с вероятностью ``extra_tag_chance`` берётся одна случайная.
        extra_tag_chance: Вероятность (0..1) уйти в франшиза-запрос вместо базового.
        ratings: Пул рейтингов; на каждый запрос берётся один случайный. Допустимые —
            ``g`` (general), ``s`` (sensitive), ``q`` (questionable), ``e`` (explicit).
            Команда ``/post_anime`` может задать конкретный рейтинг вручную.
        excluded_tags: Теги, по которым посты отсеиваются (проверка по tag_string поста).
        min_score: Минимальный Danbooru score для франшиза-запроса (``score:>=N``).
        limit: Сколько постов запрашивать за один запрос к API.
        cache_size: Размер кеша последних опубликованных постов (память + БД).
        schedule: Настройки расписания публикации.
    """

    base_tags: list[str] = ["1girl", "2girls"]
    extra_tags: list[str] = [
        "genshin_impact",
        "blue_archive",
        "persona",
    ]
    extra_tag_chance: float = Field(default=0.6, ge=0.0, le=1.0)
    ratings: list[str] = ["g", "s"]
    excluded_tags: list[str] = [
        "guro",
        "comic",
        "text_focus",
        "monochrome",
    ]
    min_score: int = 30
    limit: int = 100
    cache_size: int = 2000
    schedule: AnimeScheduleConfig = AnimeScheduleConfig()


class MusicVoiceConfig(BaseModel):
    """Конфигурация голосового подключения для музыки.

    Attributes:
        connection_timeout: Таймаут подключения к голосовому каналу (секунды)
        inactive_timeout: Сколько секунд бот ждёт в пустом канале/без музыки
            прежде чем автоматически отключиться
    """

    connection_timeout: float = 30.0
    inactive_timeout: int = 300


class LavalinkConfig(BaseModel):
    """Конфигурация подключения к Lavalink-ноде.

    Хост, порт и пароль обычно приходят из переменных окружения
    (`LAVALINK_HOST`, `LAVALINK_PORT`, `LAVALINK_SERVER_PASSWORD`),
    но имеют разумные дефолты для разработки.

    Attributes:
        host: Хост Lavalink-ноды (в docker-сети это имя сервиса)
        port: Порт Lavalink REST/WebSocket API
        password: Пароль для аутентификации с Lavalink
        secure: Использовать HTTPS/WSS (для удалённых нод за TLS-прокси)
        identifier: Идентификатор ноды в логах wavelink
        search_limit: Сколько результатов показывать при текстовом поиске
        default_volume: Громкость по умолчанию для нового плеера (0-1000)
        max_volume: Верхняя граница для команды /volume
        queue_page_size: Сколько треков выводить на одной странице /queue
    """

    host: str = "lavalink"
    port: int = 2333
    password: str = "youshallnotpass"
    secure: bool = False
    identifier: str = "MAIN"
    search_limit: int = 10
    default_volume: int = 50
    max_volume: int = 200
    queue_page_size: int = 10


class MusicConfig(BaseModel):
    """Конфигурация музыкального модуля.

    Attributes:
        lavalink: Параметры подключения к Lavalink
        voice: Таймауты голосового подключения и автодисконнекта
    """

    lavalink: LavalinkConfig = LavalinkConfig()
    voice: MusicVoiceConfig = MusicVoiceConfig()


class GiveawayConfig(BaseModel):
    """Конфигурация модуля розыгрышей.

    Attributes:
        min_duration: Минимальная длительность розыгрыша (секунды)
        max_duration: Максимальная длительность розыгрыша (секунды)
        max_description_length: Максимальная длина описания розыгрыша
        participation_emoji: Эмодзи для участия в розыгрыше
    """

    min_duration: int = 10
    max_duration: int = 604800  # 7 дней
    max_description_length: int = 4000
    participation_emoji: str = "🎉"


class TwitchConfig(BaseModel):
    """Конфигурация Twitch модуля.

    Attributes:
        check_interval: Интервал проверки стримов (секунды)
        startup_delay: Задержка при первом запуске (секунды)
        embed_color: Цвет эмбедов Twitch (hex)
    """

    check_interval: int = 60
    startup_delay: int = 30
    embed_color: str = "#6441A4"


class PenisConfig(BaseModel):
    """Конфигурация команды измерения пениса.

    Attributes:
        min_length: Минимальная длина пениса
        max_length: Максимальная длина пениса
        nuance_chance: Шанс (0.0-1.0) добавить шуточную строку-нюанс к обычной выдаче
        nuance_text: Текст строки-нюанса
        not_found_user_ids: ID пользователей, для которых вместо измерения шлётся
            шуточное сообщение об ошибке
        not_found_text: Текст шуточного сообщения об "ошибке"
    """

    min_length: int = 0
    max_length: int = 25
    nuance_chance: float = 0.10
    nuance_text: str = "...но есть нюанс, это у тебя в жопе"
    not_found_user_ids: list[int] = []
    not_found_text: str = "ошибка, пенис не найден"


class DeathbattleDamageConfig(BaseModel):
    """Конфигурация урона для deathbattle.

    Attributes:
        oneshot_chance: Шанс на ваншот (0.0-1.0)
        high_damage_chance: Шанс на высокий урон (включая ваншот)
        medium_damage_chance: Шанс на средний урон (включая высокий)
        oneshot_damage: Урон ваншота
        high_damage_min: Минимальный высокий урон
        high_damage_max: Максимальный высокий урон
        medium_damage_min: Минимальный средний урон
        medium_damage_max: Максимальный средний урон
        low_damage_min: Минимальный низкий урон
        low_damage_max: Максимальный низкий урон
    """

    oneshot_chance: float = 0.01
    high_damage_chance: float = 0.41
    medium_damage_chance: float = 0.61
    oneshot_damage: int = 100
    high_damage_min: int = 20
    high_damage_max: int = 30
    medium_damage_min: int = 10
    medium_damage_max: int = 20
    low_damage_min: int = 1
    low_damage_max: int = 10


class DeathbattleConfig(BaseModel):
    """Конфигурация deathbattle.

    Attributes:
        initial_hp: Начальное здоровье участников
        turn_delay: Задержка между ходами в секундах
        max_event_log: Максимальное количество событий в логе
        avatar_size: Размер аватаров в пикселях
        damage: Настройки урона
    """

    initial_hp: int = 100
    turn_delay: int = 2
    max_event_log: int = 3
    avatar_size: int = 128
    damage: DeathbattleDamageConfig = DeathbattleDamageConfig()


class QuotesConfig(BaseModel):
    """Конфигурация модуля quotes для отправки случайных изображений.

    Attributes:
        assets_path: Путь к папке с изображениями
        supported_extensions: Поддерживаемые расширения файлов
        view_timeout: Таймаут для UI компонентов в секундах
        max_folders_in_select: Максимальное количество папок в select menu
    """

    assets_path: str = "assets/quotes"
    supported_extensions: list[str] = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
    view_timeout: int = 300  # 5 минут
    max_folders_in_select: int = 25  # Discord лимит для select options


class FunConfig(BaseModel):
    """Конфигурация развлекательных команд.

    Attributes:
        penis: Настройки команды измерения пениса
        deathbattle: Настройки deathbattle
        quotes: Настройки модуля quotes
    """

    penis: PenisConfig = PenisConfig()
    deathbattle: DeathbattleConfig = DeathbattleConfig()
    quotes: QuotesConfig = QuotesConfig()


class ActivityReportsConfig(BaseModel):
    """Конфигурация отчетов активности.

    Attributes:
        chunk_delay: Задержка между частями отчета в секундах
    """

    chunk_delay: int = 1


class ActivityConfig(BaseModel):
    """Конфигурация модуля активности.

    Attributes:
        view_timeout: Таймаут для View в секундах
        reports: Настройки отчетов
    """

    view_timeout: int = 86400  # 24 часа
    reports: ActivityReportsConfig = ActivityReportsConfig()


class WrappedScheduleConfig(BaseModel):
    """Расписание автоматических wrapped-постов (время — по МСК).

    Месячный пост триггерится 1-го числа существующей задачей активности;
    годовой и персональный — отдельной ежедневной проверкой даты.

    Attributes:
        hour: Час запуска (МСК).
        minute: Минута запуска (МСК).
        yearly_month: Месяц годового серверного wrapped.
        yearly_day: День годового серверного wrapped.
        personal_month: Месяц персональной ЛС-рассылки.
        personal_day: День персональной ЛС-рассылки.
        personal_enabled: Включена ли персональная рассылка в ЛС.
    """

    hour: int = 12
    minute: int = 2
    yearly_month: int = 12
    yearly_day: int = 31
    personal_month: int = 12
    personal_day: int = 25
    personal_enabled: bool = True


class UserStatsConfig(BaseModel):
    """Конфигурация трекинга сообщений/голоса и wrapped-сводок.

    Голосовое время считается «умно»: только пока пользователь не в AFK-канале,
    не заглушён на приём и в канале есть как минимум ``min_humans_in_channel``
    живых участников.

    Attributes:
        count_while_muted: Засчитывать ли время с выключенным микрофоном (слушает).
        min_humans_in_channel: Минимум живых участников в канале для зачёта.
        voice_min_record: Минимальная длительность сегмента для записи (сек).
        voice_max_record: Верхний порог сегмента — защита от аномалий (сек).
        voice_periodic_save: Интервал периодического сохранения голоса (сек).
        top_limit: Сколько позиций показывать в топах wrapped.
        dm_send_delay: Задержка между ЛС при персональной рассылке (сек).
        data_since: Дата начала сбора данных для сноски в wrapped (YYYY-MM-DD).
        schedule: Расписание автоматических постов.
    """

    count_while_muted: bool = True
    min_humans_in_channel: int = 2
    voice_min_record: int = 60
    voice_max_record: int = 86400
    voice_periodic_save: int = 300
    top_limit: int = 5
    dm_send_delay: float = 0.5
    data_since: str | None = None
    schedule: WrappedScheduleConfig = WrappedScheduleConfig()


class DotaConfig(BaseModel):
    """Конфигурация модуля Dota 2.

    Attributes:
        match_view_timeout: Таймаут для View кнопок матча в секундах
    """

    match_view_timeout: int = 180  # 3 минуты


class PartyConfig(BaseModel):
    """Конфигурация модуля сбора пати.

    Attributes:
        initiator_emoji: Эмодзи, отображаемое рядом с инициатором пати
            (он автоматически в списке готовых).
        min_duration_minutes: Минимальная длительность сбора в минутах.
        max_duration_minutes: Максимальная длительность сбора в минутах.
        min_count: Минимальное число участников.
        max_count: Максимальное число участников (Discord-лимит на пинги).
        command_cooldown_seconds: Кулдаун команды /party на одного пользователя.
        button_cooldown_seconds: Кулдаун между нажатиями кнопок «Готов» / «Не готов»
            на одного пользователя в одном пати.
        dm_send_delay: Задержка между отправкой DM, чтобы не упереться в rate-limit.
        finished_message_template: Шаблон сообщения по истечении таймера, если
            набрали полный состав. Поддерживает плейсхолдеры
            {ready_pings}, {role}, {comment}.
        empty_finished_message: Шаблон сообщения, если состав не набран.
            Поддерживает {role}, {comment}.
    """

    initiator_emoji: str = "👑"
    min_duration_minutes: int = 1
    max_duration_minutes: int = 240
    min_count: int = 1
    max_count: int = 25
    command_cooldown_seconds: int = 3600
    button_cooldown_seconds: int = 60
    dm_send_delay: float = 0.1
    finished_message_template: str = (
        "Пати собрано! {ready_pings} — кто не пришёл, тот пидарас. ({role}: {comment})"
    )
    empty_finished_message: str = "Никого не собрали в пати на {role} ({comment})."


class TopReactionsConfig(BaseModel):
    """Конфигурация лидерборда сообщений с реакциями.

    Attributes:
        live_top: Сколько позиций показывать в режиме `month` / `year` (одна страница).
        all_time_top: Сколько позиций показывать в режиме `all` (с пагинацией).
        per_page: Сколько позиций на одной странице при пагинации.
        content_preview_length: До какой длины обрезать текст сообщения **при сохранении** в БД.
        preview_inline_length: До какой длины обрезать превью сообщения **в embed**
            (более короткое значение защищает от длинных сообщений, разрывающих лейаут).
        view_timeout: Таймаут View (кнопок пагинации) в секундах.
        ignored_message_ids: Ручной чёрный список id сообщений, которые не должны попадать
            в лидерборд (применяется и при сборе, и при выдаче).
        ignore_role_reaction_message: Автоматически исключать сообщение role-реакций
            (id берётся динамически из RoleReactionDataManager).
    """

    live_top: int = 10
    all_time_top: int = 50
    per_page: int = 10
    content_preview_length: int = 200
    preview_inline_length: int = 80
    view_timeout: int = 300
    ignored_message_ids: list[int] = []
    ignore_role_reaction_message: bool = True


class UserReaction(BaseModel):
    """Конфигурация одной реакции на сообщение пользователя."""

    chance: float = Field(..., ge=0.0, le=1.0)  # Вероятность от 0.0 до 1.0
    response: str


class ReactionsConfig(BaseModel):
    """Конфигурация реакций на сообщения."""

    user_reactions: dict[int, list[UserReaction]] = {}


class UpdateSettings(BaseModel):
    """Конфигурация модуля обновления.

    Attributes:
        restart_command: Команда для перезапуска бота (опционально)
    """

    restart_command: str | None = None


class Messages(BaseModel):
    """Конфигурация текстовых сообщений.

    Attributes:
        errors: Словарь сообщений об ошибках
        success: Словарь сообщений об успешных операциях
        info: Словарь информационных сообщений
    """

    errors: dict[str, str] = {
        "no_permissions": "У вас нет прав для выполнения этой команды.",
        "invalid_argument": "Неверный аргумент: {error}",
        "unknown_error": "Произошла неизвестная ошибка: {error}",
        "twitch_api_not_configured": (
            "Не указаны TWITCH_CLIENT_ID и/или TWITCH_CLIENT_SECRET в конфигурации бота."
        ),
        "anime_channel_not_configured": "Канал для публикации аниме не настроен или не найден.",
        "stratz_api_key_missing": "STRATZ_API_KEY не найден в конфигурации бота.",
    }
    success: dict[str, str] = {
        "purge_complete": "Удалено {count} сообщений",
        "link_added": "Аккаунт Dota 2 с ID {player_id} успешно привязан.",
        "restart_initiated": "🔄 Перезапуск бота...",
    }
    info: dict[str, str] = {
        "no_linked_accounts": (
            "У вас нет привязанных аккаунтов Dota 2. Используйте `/link PLAYER_ID`."
        ),
        "queue_empty": "ℹ️ Очередь пуста",
        "nothing_playing": "⏹️ Ничего не играет",
    }


class BotSettings(BaseSettings):
    """Основные настройки бота.

    Attributes:
        bot_token: Токен Discord бота
        stratz_api_key: API ключ Stratz для Dota 2
        prefix: Префикс команд бота
        environment: Окружение запуска
        twitch_client_id: Client ID для Twitch API (опционально)
        twitch_client_secret: Client Secret для Twitch API (опционально)
        proxy_url: URL прокси сервера (опционально)
        channels: Конфигурация каналов
        timeouts: Конфигурация таймаутов
        limits: Конфигурация лимитов
        colors: Конфигурация цветов
        messages: Конфигурация сообщений
    """

    # Основные настройки из .env
    bot_token: str = Field(default="test_token_here", alias="BOT_TOKEN")
    stratz_api_key: str = Field(default="test_stratz_key_here", alias="STRATZ_API_KEY")
    prefix: str = Field(default="!", alias="BOT_PREFIX")
    environment: Environment = Field(default=Environment.PRODUCTION, alias="BOT_ENVIRONMENT")

    # Опциональные API ключи
    twitch_client_id: str | None = Field(default=None, alias="TWITCH_CLIENT_ID")
    twitch_client_secret: str | None = Field(default=None, alias="TWITCH_CLIENT_SECRET")
    proxy_url: str | None = Field(default=None, alias="PROXY_URL")

    # Danbooru — аутентификация для аниме-модуля (опционально, но рекомендуется:
    # без неё работает анонимно с лимитом в 2 тега на запрос).
    danbooru_login: str | None = Field(default=None, alias="DANBOORU_LOGIN")
    danbooru_api_key: str | None = Field(default=None, alias="DANBOORU_API_KEY")

    # Lavalink — параметры подключения берутся из переменных окружения и затем
    # переносятся в music.lavalink через model_validator ниже.
    lavalink_host: str | None = Field(default=None, alias="LAVALINK_HOST")
    lavalink_port: int | None = Field(default=None, alias="LAVALINK_PORT")
    lavalink_password: str | None = Field(default=None, alias="LAVALINK_SERVER_PASSWORD")

    # Конфигурационные блоки
    channels: ChannelConfig = ChannelConfig()
    timeouts: TimeoutConfig = TimeoutConfig()
    limits: LimitConfig = LimitConfig()
    colors: ColorConfig = ColorConfig()
    messages: Messages = Messages()
    anime: AnimeConfig = AnimeConfig()
    music: MusicConfig = MusicConfig()
    giveaway: GiveawayConfig = GiveawayConfig()
    twitch: TwitchConfig = TwitchConfig()
    fun: FunConfig = FunConfig()
    activity: ActivityConfig = ActivityConfig()
    user_stats: UserStatsConfig = UserStatsConfig()
    dota: DotaConfig = DotaConfig()
    update: UpdateSettings = UpdateSettings()
    reactions: ReactionsConfig = ReactionsConfig()
    top_reactions: TopReactionsConfig = TopReactionsConfig()
    party: PartyConfig = PartyConfig()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_nested_delimiter": "__",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _apply_lavalink_env_overrides(self) -> "BotSettings":
        """Переносит плоские LAVALINK_* env-переменные в вложенный music.lavalink.

        Это позволяет .env держать привычные плоские имена (LAVALINK_HOST,
        LAVALINK_PORT, LAVALINK_SERVER_PASSWORD), не заставляя пользователя
        писать MUSIC__LAVALINK__HOST=... с двойным подчёркиванием.
        """
        if self.lavalink_host is not None:
            self.music.lavalink.host = self.lavalink_host
        if self.lavalink_port is not None:
            self.music.lavalink.port = self.lavalink_port
        if self.lavalink_password is not None:
            self.music.lavalink.password = self.lavalink_password
        return self

    @classmethod
    def load_from_yaml(cls, config_file: str = "config/bot_settings.yaml") -> "BotSettings":
        """Загружает настройки из YAML файла.

        Args:
            config_file: Путь к YAML файлу с настройками

        Returns:
            Экземпляр BotSettings с загруженными настройками
        """
        yaml_data: dict[str, Any] = {}
        config_path = Path(config_file)
        if config_path.exists():
            try:
                with open(config_path, encoding="utf-8") as f:
                    yaml_data = yaml.safe_load(f) or {}

                # Проверяем, что yaml_data является словарем
                if not isinstance(yaml_data, dict):
                    raise ValueError(
                        f"YAML файл {config_file} должен содержать словарь, "
                        f"получен {type(yaml_data)}"
                    )

            except Exception as e:
                raise ValueError(f"Ошибка при загрузке YAML файла {config_file}: {e}") from e

        return cls(**yaml_data)

    def get_discord_color(self, color_name: str) -> "discord.Color":
        """Получает цвет Discord по имени.

        Args:
            color_name: Имя цвета из конфигурации

        Returns:
            Объект discord.Color
        """
        import discord

        hex_color = getattr(self.colors, color_name, self.colors.default)
        return discord.Color(int(hex_color[1:], 16))


# Глобальный экземпляр
_settings: BotSettings | None = None


def get_settings() -> BotSettings:
    """Получает экземпляр настроек бота.

    Returns:
        Глобальный экземпляр настроек бота
    """
    global _settings
    # В тестах всегда создаем новый экземпляр для учета изменений переменных окружения
    import sys

    if "pytest" in sys.modules:
        return BotSettings.load_from_yaml()

    if _settings is None:
        _settings = BotSettings.load_from_yaml()
    return _settings


def reload_settings() -> None:
    """Перезагружает настройки бота.

    Note:
        Сбрасывает глобальный кэш и загружает настройки заново
    """
    global _settings
    _settings = BotSettings.load_from_yaml()
