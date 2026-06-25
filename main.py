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

import discord
from discord import Intents, app_commands
from discord.ext import commands

from config import get_settings
from utils.database import DB_PATH, close_database, initialize_database
from utils.error_handler import handle_app_command_error
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


class AppCommandTree(app_commands.CommandTree):
    """Дерево slash-команд с единым обработчиком ошибок.

    Всё, что не поймал ``@command_error_handler`` внутри тела команды, прилетает
    в ``on_error`` вместо «interaction failed» у пользователя.
    """

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        await handle_app_command_error(interaction, error)


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
        sys.exit(1)

    # Создание экземпляра бота с префиксом из конфига
    bot_instance: MyBot = MyBot(
        command_prefix=settings.prefix, intents=intents, tree_cls=AppCommandTree
    )
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
    bot_instance: MyBot = MyBot(
        command_prefix=settings.prefix, intents=intents, tree_cls=AppCommandTree
    )
    bot_instance.settings = settings
    bot_instance.log_file_path = str(log_path)
    bot = bot_instance


async def load_cogs() -> None:
    """Сканирует ``cogs/`` и загружает все коги + обработчики из ``handlers/``.

    Fail-fast: при ошибке загрузки любого кога или обработчика выбрасывает
    исключение наружу. Молча проглатывать импорт-ошибки опасно — бот мог
    запуститься без половины функционала и об этом узнавали только в проде.
    """
    logger.info("Загрузка когов команд...")
    cogs_dir = Path("./cogs")
    for filepath in cogs_dir.glob("*.py"):
        if filepath.name == "__init__.py":
            continue
        cog_module = f"cogs.{filepath.stem}"
        try:
            await bot.load_extension(cog_module)
        except Exception:
            logger.exception("Ошибка при загрузке кога %s", filepath.name)
            raise

    logger.info("Загрузка обработчиков событий...")
    try:
        await bot.load_extension("handlers.events")
        logger.info("Загружены обработчики событий")
    except Exception:
        logger.exception("Ошибка при загрузке handlers.events")
        raise

    logger.info("Загрузка обработчика сообщений...")
    try:
        await bot.load_extension("handlers.message_handler")
        logger.info("Загружен обработчик сообщений")
    except Exception:
        logger.exception("Ошибка при загрузке handlers.message_handler")
        raise


async def main() -> None:
    """
    Основная асинхронная функция для инициализации и запуска бота.

    Выполняет следующие действия:
    1. Инициализирует базу данных (Tortoise ORM)
    2. Загружает кэш Dota API (теперь через ORM)
    3. Загружает коги и обработчики
    4. Запускает бота с токеном из конфигурации

    Raises:
        Exception: При ошибке запуска бота, ошибка логируется и программа завершается.
    """
    logger.info(f"Используется файл базы данных: {DB_PATH}")
    await initialize_database()

    # Инициализация кэша Dota API теперь происходит внутри модуля при первом запросе
    # или мы можем явно вызвать init, если он нужен.

    await load_cogs()
    try:
        await bot.start(settings.bot_token)
    except Exception as e:
        logger.critical(f"Не удалось запустить бота: {e}")
    finally:
        if not bot.is_closed():
            await bot.close()

        # Закрываем шаренные aiohttp-сессии модулей, чтобы не светить
        # «Unclosed client session» в логи при shutdown.
        from utils.deathbattle_utils import close_session as close_deathbattle_session
        from utils.dota_api import close_session as close_dota_session

        await close_dota_session()
        await close_deathbattle_session()
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
