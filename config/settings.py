"""Модели настроек бота на основе Pydantic."""

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore
from pydantic import BaseModel, Field
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

    Attributes:
        logging: ID канала для логов бота
        anime: ID канала для публикации аниме (опционально)
        twitch: ID канала для уведомлений Twitch
        activity_reports: ID канала для отчетов активности
        role_reactions_default: ID канала по умолчанию для ролей (опционально)
    """

    logging: int = 1365045098785542224
    anime: int | None = None
    twitch: int = 1113813039083442296
    activity_reports: int = 573665353327181824
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
    """Конфигурация аниме-модуля.

    Attributes:
        tags: Список тегов для поиска изображений на safebooru.org
        excluded_tags: Список тегов для исключения из поиска (добавляются с префиксом -)
        max_tags_per_request: Максимальное количество тегов для одного запроса
        rating: Минимальный рейтинг изображений (safe, questionable, explicit)
        schedule: Настройки расписания публикации
    """

    tags: list[str] = [
        "anime",
        "1girl",
        "solo",
        "cute",
        "kawaii",
        "moe",
        "school_uniform",
        "long_hair",
        "short_hair",
        "blue_eyes",
        "brown_eyes",
        "smile",
        "blush",
        "cat_ears",
        "headphones",
        "glasses",
    ]
    excluded_tags: list[str] = [
        "nude",
        "nsfw",
        "explicit",
        "underwear",
        "panties",
        "bra",
        "swimsuit",
        "bikini",
    ]
    max_tags_per_request: int = 6
    rating: str = "safe"
    safebooru_limit: int = 100
    min_tag_selection: int = 1
    cache_size: int = 200
    schedule: AnimeScheduleConfig = AnimeScheduleConfig()


class MusicVoiceConfig(BaseModel):
    """Конфигурация голосового подключения для музыки.

    Attributes:
        connection_timeout: Таймаут подключения к голосовому каналу в секундах
    """

    connection_timeout: float = 30.0


class YtDlpConfig(BaseModel):
    """Конфигурация yt-dlp для музыкального модуля.

    Attributes:
        audio_quality: Качество аудио для постобработки
        audio_codec: Предпочитаемый кодек
        search_limit: Максимальное количество результатов поиска
        socket_timeout: Таймаут сокета в секундах
        retries: Количество повторных попыток
        geo_bypass_country: Страна для обхода геоблокировки
    """

    audio_quality: str = "192"
    audio_codec: str = "mp3"
    search_limit: int = 100
    socket_timeout: int = 5
    retries: int = 1
    geo_bypass_country: str = "RU"


class MusicConfig(BaseModel):
    """Конфигурация музыкального модуля.

    Attributes:
        downloads_dir: Директория для загрузки файлов
        ffmpeg_options: Опции FFmpeg для воспроизведения
        yt_dlp: Настройки yt-dlp
        voice: Настройки голосового подключения
    """

    downloads_dir: str = "downloads"
    ffmpeg_options: str = "-vn -loglevel info -hide_banner"
    yt_dlp: YtDlpConfig = YtDlpConfig()
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
    """

    min_length: int = 0
    max_length: int = 25


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


class DotaConfig(BaseModel):
    """Конфигурация модуля Dota 2.

    Attributes:
        match_view_timeout: Таймаут для View кнопок матча в секундах
    """

    match_view_timeout: int = 180  # 3 минуты


class TopReactionsConfig(BaseModel):
    """Конфигурация лидерборда сообщений с реакциями.

    Attributes:
        live_top: Сколько позиций показывать в режиме `month` / `year` (одна страница).
        all_time_top: Сколько позиций показывать в режиме `all` (с пагинацией).
        per_page: Сколько позиций на одной странице при пагинации.
        content_preview_length: До какой длины обрезать текст сообщения для отображения.
        view_timeout: Таймаут View (кнопок пагинации) в секундах.
    """

    live_top: int = 10
    all_time_top: int = 50
    per_page: int = 10
    content_preview_length: int = 200
    view_timeout: int = 300


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
    dota: DotaConfig = DotaConfig()
    update: UpdateSettings = UpdateSettings()
    reactions: ReactionsConfig = ReactionsConfig()
    top_reactions: TopReactionsConfig = TopReactionsConfig()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_nested_delimiter": "__",
        "case_sensitive": False,
        "extra": "ignore",
    }

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
