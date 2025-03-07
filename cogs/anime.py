import discord
from discord.ext import commands, tasks
import aiohttp
import logging
import random
from datetime import datetime, time
import pytz

logger = logging.getLogger("bot")

class AnimeImagePoster(commands.Cog):
    """Публикует аниме-изображения в указанный канал по расписанию"""
    
    def __init__(self, bot):
        self.bot = bot
        # ID канала для публикации (заменить на нужный ID)
        self.channel_id = 298811309640646666  # Это тот же канал cybersport из примера, замените на реальный
        
        # Запускаем задачи по расписанию
        self.morning_post.start()
        self.evening_post.start()
    
    def cog_unload(self):
        """Останавливает задачи при выгрузке кога"""
        self.morning_post.cancel()
        self.evening_post.cancel()
    
    async def get_anime_image(self):
        """Получает URL случайного аниме-изображения из API"""
        # Список различных API для получения аниме-изображений
        api_endpoints = [
            {"url": "https://api.waifu.im/search", "params": {"included_tags": "waifu", "is_nsfw": "false"}, "key": "images", "subkey": "url"},
            {"url": "https://api.waifu.pics/sfw/waifu", "params": {}, "key": "url"},
            {"url": "https://nekos.life/api/v2/img/neko", "params": {}, "key": "url"}
        ]
        
        # Случайно выбираем API для разнообразия
        api = random.choice(api_endpoints)
        
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
        """Публикует аниме-изображение в указанный канал"""
        try:
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logger.error(f"Канал с ID {self.channel_id} не найден")
                return
            
            image_url = await self.get_anime_image()
            
            if image_url:
                # Отправляем только изображение, без текста
                await channel.send(image_url)
                logger.info(f"Аниме-изображение опубликовано в канале {channel.name}")
            else:
                logger.error("Не удалось получить аниме-изображение для публикации")
        
        except Exception as e:
            logger.error(f"Ошибка при публикации аниме-изображения: {e}", exc_info=True)
    
    @tasks.loop(time=time(hour=10, minute=0))  # 10:00 утра по серверному времени
    async def morning_post(self):
        """Публикует аниме-изображение утром"""
        await self.post_anime_image()
    
    @tasks.loop(time=time(hour=18, minute=0))  # 18:00 вечера по серверному времени
    async def evening_post(self):
        """Публикует аниме-изображение вечером"""
        await self.post_anime_image()
    
    @morning_post.before_loop
    async def before_morning_post(self):
        """Ожидает готовности бота перед запуском утренней задачи"""
        await self.bot.wait_until_ready()
        logger.info("Запущена задача утренней публикации аниме-изображений")
    
    @evening_post.before_loop
    async def before_evening_post(self):
        """Ожидает готовности бота перед запуском вечерней задачи"""
        await self.bot.wait_until_ready()
        logger.info("Запущена задача вечерней публикации аниме-изображений")
    
    @commands.hybrid_command(description='Публикует случайное аниме-изображение')
    @commands.has_permissions(administrator=True)  # Только для администраторов
    async def post_anime(self, ctx):
        """Мануально публикует аниме-изображение"""
        await self.post_anime_image()
        await ctx.send("Аниме-изображение опубликовано!", ephemeral=True)

async def setup(bot):
    """Загружает ког AnimeImagePoster"""
    await bot.add_cog(AnimeImagePoster(bot))
