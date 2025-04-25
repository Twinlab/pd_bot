import discord
from discord.ext import commands, tasks
import aiohttp
import logging
import random
from datetime import datetime, time
import pytz

# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

class AnimeImagePoster(commands.Cog):
    """
    Ког для автоматической и ручной публикации случайных SFW аниме-изображений
    в заданный канал Discord.
    """
    def __init__(self, bot):
        """
        Инициализирует ког, получает ID канала из конфигурации и запускает
        фоновые задачи для публикации по расписанию.
        """
        self.bot = bot
        # Получаем ID канала из конфигурации
        self.channel_id = self.bot.config.get("ANIME_CHANNEL_ID")
        
        if not self.channel_id:
             logger.error("ANIME_CHANNEL_ID не найден в конфигурации. Задачи публикации не будут запущены.")
             return # Не запускаем задачи, если ID не найден

        # Запускаем задачи по расписанию
        self.morning_post.start()
        self.evening_post.start()
    
    def cog_unload(self):
        """Вызывается при выгрузке кога, останавливает фоновые задачи."""
        logger.info("Остановка задач публикации аниме...")
        self.morning_post.cancel()
        self.evening_post.cancel()
    
    async def get_anime_image(self) -> Optional[str]:
        """
        Асинхронно получает URL случайного SFW аниме-изображения,
        используя одно из нескольких публичных API.
        
        Returns:
            URL изображения в виде строки или None в случае ошибки.
        """
        # Список доступных API эндпоинтов
        api_endpoints = [
            {"url": "https://api.waifu.im/search", "params": {"included_tags": "waifu", "is_nsfw": "false"}, "key": "images", "subkey": "url"},
            {"url": "https://api.waifu.pics/sfw/waifu", "params": {}, "key": "url"},
            {"url": "https://nekos.life/api/v2/img/neko", "params": {}, "key": "url"} # nekos.life
        ]
        
        # Выбираем случайный эндпоинт из списка
        api = random.choice(api_endpoints)
        
        # Выполняем асинхронный GET-запрос
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(api["url"], params=api["params"]) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Извлекаем URL изображения из ответа в зависимости от API
                        if api["key"] == "images":
                            # Для API типа waifu.im
                            return data[api["key"]][0][api["subkey"]]
                        else:
                            # Для API типа waifu.pics или nekos.life
                            return data[api["key"]]
                    else:
                        logger.error(f"Ошибка при запросе к API: {response.status}")
                        return None
            except Exception as e:
                logger.error(f"Ошибка при получении аниме-изображения: {e}", exc_info=True)
                return None
    
    async def post_anime_image(self):
        """
        Получает URL аниме-изображения и публикует его в настроенный канал.
        Логирует результат или ошибки.
        """
        try:
            # Получаем объект канала по ID
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logger.error(f"Канал с ID {self.channel_id} не найден")
                return
            
            # Получаем URL изображения
            image_url = await self.get_anime_image()
            
            if image_url:
                # Отправляем URL в канал (Discord автоматически отобразит изображение)
                await channel.send(image_url)
                logger.info(f"Аниме-изображение опубликовано в канале {channel.name}")
            else:
                logger.error("Не удалось получить аниме-изображение для публикации")
        
        except Exception as e:
            logger.error(f"Ошибка в post_anime_image: {e}", exc_info=True)
    
    # --- Фоновые задачи ---
    
    @tasks.loop(time=time(hour=10, minute=0)) # Указываем время запуска (по UTC, если не задан tzinfo)
    async def morning_post(self):
        """Задача, выполняющаяся ежедневно в 10:00 UTC для утренней публикации."""
        logger.info("Запуск утренней публикации аниме...")
        await self.post_anime_image()
    
    @tasks.loop(time=time(hour=18, minute=0)) # Указываем время запуска (по UTC, если не задан tzinfo)
    async def evening_post(self):
        """Задача, выполняющаяся ежедневно в 18:00 UTC для вечерней публикации."""
        logger.info("Запуск вечерней публикации аниме...")
        await self.post_anime_image()
    
    @morning_post.before_loop
    async def before_morning_post(self):
        """Ожидает готовности бота перед первым запуском утренней задачи."""
        await self.bot.wait_until_ready()
        logger.info("Задача morning_post готова к запуску.")
    
    @evening_post.before_loop
    async def before_evening_post(self):
        """Ожидает готовности бота перед первым запуском вечерней задачи."""
        await self.bot.wait_until_ready()
        logger.info("Задача evening_post готова к запуску.")
    
    # --- Команды ---
    
    @commands.hybrid_command(description='Опубликовать случайное аниме-изображение сейчас')
    @commands.has_permissions(administrator=True)  # Только для администраторов
    @command_error_handler
    async def post_anime(self, ctx):
        """
        Команда для администраторов, позволяющая вручную запустить
        публикацию случайного аниме-изображения в настроенный канал.
        """
        if not self.channel_id:
             await ctx.send("Ошибка: ID канала для публикации аниме не настроен.", ephemeral=True)
             return
             
        await self.post_anime_image()
        await ctx.send("Аниме-изображение опубликовано!", ephemeral=True)

async def setup(bot):
    """Загружает ког AnimeImagePoster"""
    await bot.add_cog(AnimeImagePoster(bot))
