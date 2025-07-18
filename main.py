"""
Основной файл для запуска Discord бота, инициализации и загрузки компонентов.

Этот модуль содержит точку входа в приложение, настройку логирования,
инициализацию бота Discord и загрузку всех необходимых компонентов.
Он отвечает за:
- Настройку системы логирования
- Загрузку конфигурации из файла
- Инициализацию бота с нужными интентами
- Загрузку когов и обработчиков событий
- Запуск бота
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from discord import Intents
from discord.ext import commands

from config import get_settings
from utils import dota_api
from utils.database import DB_PATH, initialize_database
from utils.logging_utils import setup_logging

# Настройка расширенного логирования
log_path = setup_logging(
    log_dir="logs",
    log_level=logging.INFO,
    enable_json_logs=True,
    enable_console_logs=True,
)

# Получаем логгер для текущего модуля
logger: logging.Logger = logging.getLogger("bot.main")

# Настройка интентов бота
intents: Intents = Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True
intents.presences = True


# Определение кастомного класса бота
class MyBot(commands.Bot):
    """Кастомный класс бота, наследуемый от commands.Bot.

    Добавляет атрибуты settings и log_file_path для доступа к конфигурации
    и пути к файлу логов соответственно.
    """

    settings: Any  # BotSettings
    log_file_path: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Инициализирует кастомного бота.

        Args:
            *args: Позиционные аргументы для commands.Bot.
            **kwargs: Именованные аргументы для commands.Bot.
        """
        super().__init__(*args, **kwargs)
        # Атрибуты config и log_file_path будут установлены после инициализации экземпляра


def initialize_bot() -> MyBot:
    """Инициализирует бота с настройками."""
    # Загрузка конфигурации ДО создания экземпляра бота
    settings = get_settings()

    # Проверка наличия токена ДО создания бота (только если не в тестах)
    if not settings.bot_token or (
        settings.bot_token == "test_token_here" and "pytest" not in sys.modules
    ):
        logger.critical("Токен бота (BOT_TOKEN) не найден в .env! Запуск невозможен.")
        exit()

    # Создание экземпляра бота с префиксом из конфига
    bot_instance: MyBot = MyBot(command_prefix=settings.prefix, intents=intents)
    bot_instance.settings = settings  # Новый способ доступа
    bot_instance.log_file_path = str(log_path)  # Передаём путь к текущему логу в cog

    return bot_instance


# Глобальные переменные для совместимости с тестами
settings = get_settings()

# Создание экземпляра бота
if "pytest" not in sys.modules:
    # В продакшене используем полную инициализацию
    bot: MyBot = initialize_bot()
else:
    # В тестах создаем бота без проверок токена
    bot_instance: MyBot = MyBot(command_prefix=settings.prefix, intents=intents)
    bot_instance.settings = settings
    bot_instance.log_file_path = str(log_path)
    bot = bot_instance


async def load_cogs() -> None:
    """
    Сканирует директорию cogs/ для загрузки когов команд и загружает обработчики из handlers/.

    Функция выполняет:
    1. Загрузку всех Python-файлов из директории cogs/ как расширения бота
    2. Загрузку обработчика событий из handlers.events
    3. Загрузку обработчика сообщений из handlers.message_handler

    Raises:
        Exception: При ошибке загрузки кога или обработчика, ошибка логируется,
                  но выполнение продолжается.
    """
    logger.info("Загрузка когов команд...")
    cogs_dir = Path("./cogs")
    for filepath in cogs_dir.glob("*.py"):
        if filepath.name != "__init__.py":
            cog_module = f"cogs.{filepath.stem}"
            try:
                await bot.load_extension(cog_module)
                # Мы не логируем загрузку здесь, так как это делается в самих когах
                # Утилита should_log_cog_load используется в когах для предотвращения дублирования
            except Exception as e:
                logger.error(f"Ошибка при загрузке кога {filepath.name}: {e}")

    logger.info("Загрузка обработчиков событий...")
    try:
        await bot.load_extension("handlers.events")
        logger.info("Загружены обработчики событий")
    except Exception as e:
        logger.error(f"Ошибка при загрузке обработчиков событий: {e}")

    logger.info("Загрузка обработчика сообщений...")
    try:
        await bot.load_extension("handlers.message_handler")
        logger.info("Загружен обработчик сообщений")
    except Exception as e:
        logger.error(f"Ошибка при загрузке обработчика сообщений: {e}")


async def main() -> None:
    """
    Основная асинхронная функция для инициализации и запуска бота.

    Выполняет следующие действия:
    1. Инициализирует базу данных
    2. Загружает кэш Dota API с диска
    3. Загружает коги и обработчики
    4. Запускает бота с токеном из конфигурации

    Raises:
        Exception: При ошибке запуска бота, ошибка логируется и программа завершается.
    """
    logger.info(f"Используется файл базы данных: {DB_PATH}")
    await initialize_database()
    logger.info("Загрузка кэша Dota API с диска...")
    await dota_api.load_cache_from_disk()
    await load_cogs()
    try:
        await bot.start(settings.bot_token)
    except Exception as e:
        logger.critical(f"Не удалось запустить бота: {e}")


if __name__ == "__main__":
    asyncio.run(main())
