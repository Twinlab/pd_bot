import discord
import asyncio
import os
import logging
from discord.ext import commands
from discord import Intents
 
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("bot")
 
# Импорт конфигурации
from config import load_config
 
# Настройка интентов бота
intents = Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True
intents.presences = True

# Создание экземпляра бота
bot = commands.Bot(command_prefix="!", intents=intents)
 
# Функция для загрузки всех когов
async def load_cogs():
    """Загружает все доступные коги"""
    # Загрузка когов из директории cogs
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and filename != "__init__.py":
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                logger.info(f"Загружен ког: cogs.{filename[:-3]}")
            except Exception as e:
                logger.error(f"Ошибка при загрузке кога {filename}: {e}")
    
    # Загрузка обработчиков событий
    try:
        await bot.load_extension('handlers.events')
        logger.info("Загружены обработчики событий")
    except Exception as e:
        logger.error(f"Ошибка при загрузке обработчиков событий: {e}")
    
    # Загрузка обработчика сообщений
    try:
        await bot.load_extension('handlers.message_handler')
        logger.info("Загружен обработчик сообщений")
    except Exception as e:
        logger.error(f"Ошибка при загрузке обработчика сообщений: {e}")
 
# Запуск бота
async def main():
    # Загрузка конфигурации
    config = load_config()
    
    # Проверка наличия токена
    if not config.get("BOT_TOKEN"):
        logger.critical("Токен бота не найден в config.json!")
        return
    
    # Загрузка когов
    await load_cogs()
    
    # Запуск бота
    try:
        await bot.start(config["BOT_TOKEN"])
    except Exception as e:
        logger.critical(f"Не удалось запустить бота: {e}")
 
# Точка входа
if __name__ == "__main__":
    asyncio.run(main())