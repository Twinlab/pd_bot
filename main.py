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
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import discord
from discord import Intents, app_commands
from discord.ext import commands

from config import get_settings
from utils.database import DB_PATH, close_database, initialize_database
from utils.dota_api import prune_expired_cache
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

BOT_CLOSE_TIMEOUT_SECONDS = 3.0
RESOURCE_CLOSE_TIMEOUT_SECONDS = 2.0
DATABASE_CLOSE_TIMEOUT_SECONDS = 2.0


def get_runtime_revision() -> str:
    """Возвращает идентификатор сборки для логов и production-диагностики."""
    return os.getenv("BOT_REVISION", "").strip() or "development"


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

    async def setup_hook(self) -> None:
        """Синхронизирует дерево команд один раз за процесс.

        ``setup_hook`` вызывается после логина, но до коннекта к gateway и ровно
        один раз за запуск — поэтому здесь не нужен ручной флаг «синкали уже», как
        было в ``on_ready`` (тот срабатывает на каждый reconnect). Коги к этому
        моменту уже загружены в :func:`main` до ``bot.start``, так что дерево
        заполнено. Persistent-вью по-прежнему регистрируются в ``cog_load`` когов.
        """
        await self._sync_commands()

    async def _sync_commands(self) -> None:
        """Синхронизирует slash-команды.

        Single-guild дизайн: при заданном ``guild_id`` команды живут только в этой
        гильдии и применяются мгновенно; глобальную копию очищаем, иначе команды
        задваиваются. Без ``guild_id`` — обычный глобальный синк (раскатка до часа).
        """
        guild_id = get_settings().guild_id
        logger.info("Синхронизация slash-команд...")
        try:
            if guild_id:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                scope = f"в гильдию {guild_id}"
            else:
                synced = await self.tree.sync()
                scope = "глобально (раскатка до часа; задай GUILD_ID для мгновенного синка)"
            logger.info(
                f"Синхронизировано {len(synced)} команд {scope}: "
                f"{', '.join(cmd.name for cmd in synced)}"
            )
        except Exception as e:
            logger.error(f"Не удалось синхронизировать команды: {e}")


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
    for filepath in sorted(cogs_dir.glob("*.py")):
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


async def _run_cleanup_step(
    resource_name: str,
    cleanup: Callable[[], Awaitable[None]],
    timeout_seconds: float,
) -> bool:
    """Закрывает один ресурс за ограниченное время и логирует результат."""
    started_at = asyncio.get_running_loop().time()
    try:
        async with asyncio.timeout(timeout_seconds):
            await cleanup()
    except TimeoutError:
        logger.error(
            "Таймаут %.1f с при закрытии ресурса %s",
            timeout_seconds,
            resource_name,
        )
        return False
    except Exception:
        logger.exception("Ошибка при закрытии ресурса %s", resource_name)
        return False

    elapsed = asyncio.get_running_loop().time() - started_at
    logger.info("Ресурс %s закрыт за %.2f с", resource_name, elapsed)
    return True


async def _shutdown_resources(database_initialized: bool) -> None:
    """Параллельно закрывает сетевые клиенты, затем независимо закрывает БД."""
    from utils.cs_api import close_session as close_cs_session
    from utils.deathbattle_utils import close_session as close_deathbattle_session
    from utils.dota_api import close_session as close_dota_session
    from utils.match_card import close_session as close_match_card_session
    from utils.music import close_nodes

    cleanup_steps: tuple[tuple[str, Callable[[], Awaitable[None]]], ...] = (
        ("Dota API", close_dota_session),
        ("CS API", close_cs_session),
        ("deathbattle API", close_deathbattle_session),
        ("match-card HTTP", close_match_card_session),
        ("Lavalink", close_nodes),
    )
    await asyncio.gather(
        *(
            _run_cleanup_step(name, cleanup, RESOURCE_CLOSE_TIMEOUT_SECONDS)
            for name, cleanup in cleanup_steps
        )
    )

    if database_initialized:
        await _run_cleanup_step(
            "базы данных",
            close_database,
            DATABASE_CLOSE_TIMEOUT_SECONDS,
        )


def _install_shutdown_handlers(task: asyncio.Task[Any]) -> list[signal.Signals]:
    """Отменяет main-задачу по SIGINT/SIGTERM, чтобы выполнить блок finally."""
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []

    def request_shutdown(received_signal: signal.Signals) -> None:
        if task.done() or task.cancelling():
            return
        logger.info("Получен %s, начинаю корректное завершение", received_signal.name)
        task.cancel()

    for handled_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                handled_signal,
                request_shutdown,
                handled_signal,
            )
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(handled_signal)
    return installed


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
    database_initialized = False
    current_task = asyncio.current_task()
    installed_signals = _install_shutdown_handlers(current_task) if current_task else []
    try:
        logger.info("Версия сборки: %s", get_runtime_revision())
        logger.info(f"Используется файл базы данных: {DB_PATH}")
        await initialize_database()
        database_initialized = True
        await prune_expired_cache()
        await load_cogs()
        await bot.start(settings.bot_token)
    except asyncio.CancelledError:
        logger.info("Основная задача остановлена по сигналу завершения")
    except Exception:
        logger.exception("Не удалось запустить бота")
        raise
    finally:
        loop = asyncio.get_running_loop()
        shutdown_started_at = loop.time()
        try:
            if not bot.is_closed():
                await _run_cleanup_step(
                    "Discord-клиента",
                    bot.close,
                    BOT_CLOSE_TIMEOUT_SECONDS,
                )
            await _shutdown_resources(database_initialized)
        finally:
            for handled_signal in installed_signals:
                loop.remove_signal_handler(handled_signal)
            logger.info(
                "Корректное завершение заняло %.2f с",
                loop.time() - shutdown_started_at,
            )


if __name__ == "__main__":
    asyncio.run(main())
