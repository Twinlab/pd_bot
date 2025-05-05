import discord
import asyncio
import os
from pathlib import Path
import logging
from datetime import datetime
from discord.ext import commands
from discord import Intents

# === Логирование: создаём logs/ и уникальный файл ===
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
log_filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S.log")
log_path = LOGS_DIR / log_filename

# (опционально) создаём/обновляем симлинк на последний лог
latest_symlink = LOGS_DIR / "latest.log"
try:
    if latest_symlink.exists() or latest_symlink.is_symlink():
        latest_symlink.unlink()
    latest_symlink.symlink_to(log_filename)
except Exception:
    pass  # не критично

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path, mode="a", encoding=None, delay=False),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("bot")

# Импорт конфигурации
from config import load_config
# Импорт инициализатора БД
from utils.database import initialize_database, DB_PATH
# Импорт для инициализации кэша Dota API
from utils import dota_api
 
# Настройка интентов бота
intents = Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True
intents.presences = True

# Загрузка конфигурации ДО создания экземпляра бота
config = load_config()

# Проверка наличия токена ДО создания бота
if not config.get("BOT_TOKEN"):
    logger.critical("Токен бота (BOT_TOKEN) не найден в data/config.json! Запуск невозможен.")
    exit()

# Создание экземпляра бота с префиксом из конфига
bot = commands.Bot(command_prefix=config.get("PREFIX", "!"), intents=intents)
bot.config = config
bot.log_file_path = str(log_path)  # Передаём путь к текущему логу в cog

async def load_cogs():
    """Сканирует директорию cogs/ для загрузки когов команд и загружает указанные обработчики из handlers/."""
    logger.info("Загрузка когов команд...")
    cogs_dir = Path("./cogs")
    for filepath in cogs_dir.glob("*.py"):
        if filepath.name != "__init__.py":
            cog_module = f"cogs.{filepath.stem}"
            try:
                await bot.load_extension(cog_module)
                logger.info(f"Загружен ког: {cog_module}")
            except Exception as e:
                logger.error(f"Ошибка при загрузке кога {filepath.name}: {e}")

    logger.info("Загрузка обработчиков событий...")
    try:
        await bot.load_extension('handlers.events')
        logger.info("Загружены обработчики событий")
    except Exception as e:
        logger.error(f"Ошибка при загрузке обработчиков событий: {e}")

    logger.info("Загрузка обработчика сообщений...")
    try:
        await bot.load_extension('handlers.message_handler')
        logger.info("Загружен обработчик сообщений")
    except Exception as e:
        logger.error(f"Ошибка при загрузке обработчика сообщений: {e}")

async def main():
    """Основная асинхронная функция для инициализации и запуска бота."""
    logger.info(f"Используется файл базы данных: {DB_PATH}")
    await initialize_database()
    logger.info("Загрузка кэша Dota API с диска...")
    await dota_api.load_cache_from_disk() # Загружаем кэш перед когами
    await load_cogs()
    try:
        await bot.start(config["BOT_TOKEN"])
    except Exception as e:
        logger.critical(f"Не удалось запустить бота: {e}")

if __name__ == "__main__":
    asyncio.run(main())
