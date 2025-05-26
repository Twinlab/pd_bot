"""Модели настроек бота на основе Pydantic."""

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

import yaml  # type: ignore
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    import discord


class Environment(str, Enum):
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
    anime: Optional[int] = None
    twitch: int = 1113813039083442296
    activity_reports: int = 573665353327181824
    role_reactions_default: Optional[int] = None


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


class Messages(BaseModel):
    """Конфигурация текстовых сообщений.

    Attributes:
        errors: Словарь сообщений об ошибках
        success: Словарь сообщений об успешных операциях
        info: Словарь информационных сообщений
    """

    errors: Dict[str, str] = {
        "no_permissions": "У вас нет прав для выполнения этой команды.",
        "invalid_argument": "Неверный аргумент: {error}",
        "unknown_error": "Произошла неизвестная ошибка: {error}",
        "twitch_api_not_configured": (
            "Не указаны TWITCH_CLIENT_ID и/или TWITCH_CLIENT_SECRET в конфигурации бота."
        ),
        "anime_channel_not_configured": "Канал для публикации аниме не настроен или не найден.",
        "stratz_api_key_missing": "STRATZ_API_KEY не найден в конфигурации бота.",
    }
    success: Dict[str, str] = {
        "purge_complete": "Удалено {count} сообщений",
        "link_added": "Аккаунт Dota 2 с ID {player_id} успешно привязан.",
        "restart_initiated": "🔄 Перезапуск бота...",
    }
    info: Dict[str, str] = {
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
    bot_token: str = Field(alias="BOT_TOKEN")
    stratz_api_key: str = Field(alias="STRATZ_API_KEY")
    prefix: str = Field(default="!", alias="BOT_PREFIX")
    environment: Environment = Field(default=Environment.PRODUCTION, alias="BOT_ENVIRONMENT")

    # Опциональные API ключи
    twitch_client_id: Optional[str] = Field(default=None, alias="TWITCH_CLIENT_ID")
    twitch_client_secret: Optional[str] = Field(default=None, alias="TWITCH_CLIENT_SECRET")
    proxy_url: Optional[str] = Field(default=None, alias="PROXY_URL")

    # Конфигурационные блоки
    channels: ChannelConfig = ChannelConfig()
    timeouts: TimeoutConfig = TimeoutConfig()
    limits: LimitConfig = LimitConfig()
    colors: ColorConfig = ColorConfig()
    messages: Messages = Messages()

    class Config:
        """Конфигурация Pydantic.

        Attributes:
            env_file: Файл с переменными окружения
            env_file_encoding: Кодировка файла окружения
            env_nested_delimiter: Разделитель для вложенных настроек
            case_sensitive: Чувствительность к регистру
            extra: Обработка дополнительных полей
        """

        env_file = ".env"
        env_file_encoding = "utf-8"
        env_nested_delimiter = "__"
        case_sensitive = False
        extra = "ignore"

    @classmethod
    def load_from_yaml(cls, config_file: str = "config/bot_settings.yaml") -> "BotSettings":
        """Загружает настройки из YAML файла.

        Args:
            config_file: Путь к YAML файлу с настройками

        Returns:
            Экземпляр BotSettings с загруженными настройками
        """
        yaml_data: Dict[str, any] = {}  # type: ignore
        config_path = Path(config_file)
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}

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
_settings: Optional[BotSettings] = None


def get_settings() -> BotSettings:
    """Получает экземпляр настроек бота.

    Returns:
        Глобальный экземпляр настроек бота
    """
    global _settings
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
