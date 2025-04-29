import discord
import asyncio
import os # Оставляем для listdir в handlers, если не меняем там
from pathlib import Path # Импортируем Path
import logging
from discord.ext import commands
from discord import Intents
 
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", mode="a", encoding=None, delay=False, buffering=1),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("bot")
 
# Импорт конфигурации
from config import load_config
# Импорт инициализатора БД
from utils.database import initialize_database, DB_PATH

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
    # Можно либо выйти, либо поднять исключение
    exit() # Простой выход, если токена нет

# Создание экземпляра бота с префиксом из конфига
bot = commands.Bot(command_prefix=config.get("PREFIX", "!"), intents=intents) # Используем get с дефолтным значением
bot.config = config # Прикрепляем конфиг к боту

async def load_cogs():
    """Сканирует директорию cogs/ для загрузки когов команд и загружает указанные обработчики из handlers/."""
    # Загрузка когов команд из директории cogs/
    logger.info("Загрузка когов команд...")
    cogs_dir = Path("./cogs")
    for filepath in cogs_dir.glob("*.py"):
        if filepath.name != "__init__.py":
            cog_module = f"cogs.{filepath.stem}" # stem дает имя файла без расширения
            try:
                await bot.load_extension(cog_module)
                logger.info(f"Загружен ког: {cog_module}")
            except Exception as e:
                logger.error(f"Ошибка при загрузке кога {filepath.name}: {e}")
    
    # Загрузка обработчиков событий из handlers/
    logger.info("Загрузка обработчиков событий...")
    try:
        await bot.load_extension('handlers.events')
        logger.info("Загружены обработчики событий")
    except Exception as e:
        logger.error(f"Ошибка при загрузке обработчиков событий: {e}")
    
    # Загрузка обработчика сообщений из handlers/
    logger.info("Загрузка обработчика сообщений...")
    try:
        await bot.load_extension('handlers.message_handler')
        logger.info("Загружен обработчик сообщений")
    except Exception as e:
        logger.error(f"Ошибка при загрузке обработчика сообщений: {e}")
 
async def main():
    """Основная асинхронная функция для инициализации и запуска бота."""
    # Конфигурация и бот уже созданы выше
    
    # Инициализация базы данных
    logger.info(f"Используется файл базы данных: {DB_PATH}")
    await initialize_database()
    
    # Загрузка всех когов и обработчиков
    await load_cogs()
    
    # Запуск основного цикла бота
    try:
        await bot.start(config["BOT_TOKEN"])
    except Exception as e:
        logger.critical(f"Не удалось запустить бота: {e}")
 
# Точка входа при запуске скрипта напрямую
if __name__ == "__main__":
    asyncio.run(main())
