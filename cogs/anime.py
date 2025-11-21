"""Ког для автоматической и ручной публикации SFW аниме-изображений.

Этот модуль предоставляет функциональность для автоматической публикации
аниме-изображений в заданный канал Discord по расписанию (утром и вечером),
а также команду для ручной публикации изображений администраторами.
Изображения получаются с сайта safebooru.org через их API.

Кеширование:
- Модуль ведет кеш опубликованных изображений для предотвращения повторов
- Кеш хранится как в памяти (deque), так и в базе данных (таблица anime_cache)
- При запуске бота кеш автоматически загружается из БД
- Новые изображения автоматически добавляются в кеш и сохраняются в БД
- Размер кеша в памяти ограничен настройкой cache_size в конфигурации
"""

import logging
import random
from collections import deque
from datetime import time
from typing import Any

import aiohttp
from discord.ext import commands, tasks

from config import get_settings
from utils.error_handler import command_error_handler
from utils.models import AnimeCache

logger: logging.Logger = logging.getLogger("bot.cogs.anime")  # Иерархическое имя логгера


class AnimeCog(commands.Cog):
    """Ког для публикации SFW аниме-изображений с safebooru.org.

    Автоматически и вручную публикует случайные изображения
    в заданный канал Discord. Использует настраиваемые теги
    для поиска изображений через API safebooru.org.

    Теги настраиваются в файле config/bot_settings.yaml в секции anime.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког, получает ID канала из конфигурации и запускает фоновые задачи.

        Args:
            bot: Экземпляр discord.ext.commands.Bot.
        """
        self.bot: commands.Bot = bot
        # Получаем настройки из новой системы конфигурации
        settings = get_settings()
        self.channel_id: int | None = settings.channels.anime
        self.cache_size: int = settings.anime.cache_size
        self.post_cache: deque[int] = deque(maxlen=self.cache_size)
        self._cache_loaded: bool = False  # Флаг для отслеживания загрузки кеша

        if not self.channel_id:
            logger.error("Канал для публикации аниме не настроен или не найден.")
            return  # Не запускаем задачи, если ID не найден

        # Устанавливаем время из конфигурации
        morning_time = time(
            hour=settings.anime.schedule.morning_hour, minute=settings.anime.schedule.morning_minute
        )
        evening_time = time(
            hour=settings.anime.schedule.evening_hour, minute=settings.anime.schedule.evening_minute
        )

        # Изменяем время выполнения задач
        self.morning_post.change_interval(time=morning_time)
        self.evening_post.change_interval(time=evening_time)

        # Запускаем задачи по расписанию
        self.morning_post.start()
        self.evening_post.start()

    async def _load_cache_from_db(self) -> None:
        """Загружает кеш из базы данных при первом использовании."""
        if self._cache_loaded:
            return

        try:
            # Загружаем последние N записей из БД, сортируя по времени добавления (новые первые)
            last_items = await AnimeCache.all().order_by("-added_at").limit(self.cache_size)
            
            # Сортируем их по возрастанию времени (старые первые), чтобы правильно заполнить deque
            sorted_items = sorted(last_items, key=lambda x: x.added_at)
            
            for item in sorted_items:
                self.post_cache.append(item.post_id)

            self._cache_loaded = True
            logger.info(f"Кеш аниме загружен из БД: {len(sorted_items)} элементов")
        except Exception as e:
            logger.error(f"Ошибка при загрузке кеша из БД: {e}", exc_info=True)
            self._cache_loaded = True

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога, останавливает фоновые задачи."""
        logger.info("Остановка задач публикации аниме...")
        self.morning_post.cancel()
        self.evening_post.cancel()

    async def get_anime_image(self) -> tuple[str, int] | None:
        """Асинхронно получает URL и ID случайного SFW аниме-изображения.

        Использует API safebooru.org для поиска изображений по настроенным тегам.
        Пытается найти изображение, которого нет в кэше, делая до 3 попыток.

        Returns:
            Кортеж (URL, ID) или None в случае ошибки.
        """
        # Загружаем кеш из БД при первом использовании
        await self._load_cache_from_db()

        settings = get_settings()
        max_retries = 3
        for attempt in range(max_retries):
            logger.info(f"Попытка {attempt + 1}/{max_retries} получения нового изображения...")
            # Сначала пробуем основной запрос с выбранными тегами
            result = await self._try_get_image_with_tags(settings)

            # Если основной запрос не дал результатов, пробуем fallback
            if not result:
                logger.info("Основной запрос не дал результатов, пробуем fallback с тегом '1girl'")
                result = await self._try_get_image_fallback(settings)

            if result:
                image_url, post_id = result
                if post_id not in self.post_cache:
                    logger.info(f"Найдено новое изображение (ID: {post_id})")
                    return image_url, post_id
                else:
                    logger.warning(
                        f"Изображение (ID: {post_id}) уже есть в кэше. Повторная попытка..."
                    )
            else:
                logger.warning("Не удалось получить изображение на этой попытке.")

        logger.error("Не удалось найти новое изображение после нескольких попыток.")
        return None

    async def _try_get_image_with_tags(self, settings: Any) -> tuple[str, int] | None:
        """Пробует получить изображение с выбранными тегами."""
        available_tags = settings.anime.tags

        if available_tags:
            selected_tag = random.choice(available_tags)
            selected_tags = [selected_tag]
        else:
            selected_tags = ["1girl"]

        excluded_tags = [f"-{tag}" for tag in settings.anime.excluded_tags]

        all_tags = selected_tags + excluded_tags + [f"rating:{settings.anime.rating}"]

        return await self._make_api_request(all_tags, selected_tags, settings)

    async def _try_get_image_fallback(self, settings: Any) -> tuple[str, int] | None:
        """Fallback запрос только с тегом '1girl' и исключениями."""
        # Только обязательные теги: 1girl + исключения + рейтинг
        selected_tags = ["1girl"]
        excluded_tags = [f"-{tag}" for tag in settings.anime.excluded_tags]
        all_tags = selected_tags + excluded_tags + [f"rating:{settings.anime.rating}"]

        return await self._make_api_request(all_tags, selected_tags, settings)

    async def _make_api_request(
        self, all_tags: list[str], selected_tags: list[str], settings: Any
    ) -> tuple[str, int] | None:
        """Выполняет запрос к API safebooru.org и возвращает URL и ID поста."""
        api_url = "https://safebooru.org/index.php"

        # Максимальное количество попыток найти непустую страницу
        max_page_attempts = 10

        async with aiohttp.ClientSession() as session:
            for attempt in range(max_page_attempts):
                # Используем оптимальный диапазон страниц на основе отладки
                random_page = random.randint(0, 30)  # Самый стабильный диапазон

                # Формируем параметры запроса для safebooru API
                params = {
                    "page": "dapi",
                    "s": "post",
                    "q": "index",
                    "json": "1",
                    "limit": str(settings.anime.safebooru_limit),
                    "tags": " ".join(all_tags),
                    "pid": str(random_page),
                }

                try:
                    # Выполняем запрос к API
                    async with session.get(api_url, params=params) as response:
                        if response.status == 200:
                            # Проверяем content-type перед парсингом JSON
                            content_type = response.headers.get("content-type", "")
                            if "application/json" not in content_type:
                                logger.debug(f"Неверный content-type на стр. {random_page}")
                                continue  # Пробуем следующую страницу

                            try:
                                data = await response.json()
                            except Exception:
                                logger.debug(f"Ошибка JSON на стр. {random_page}")
                                continue  # Пробуем следующую страницу

                            # Проверяем, что получили список
                            if not isinstance(data, list):
                                logger.debug(f"Не список на стр. {random_page}")
                                continue  # Пробуем следующую страницу

                            # Фильтруем посты, у которых нет ID
                            valid_posts = [p for p in data if isinstance(p, dict) and "id" in p]
                            if not valid_posts:
                                logger.debug(f"Пустая страница {random_page}, пробуем следующую...")
                                continue  # Пробуем следующую страницу

                            # Выбираем случайный пост
                            random_post = random.choice(valid_posts)
                            post_id = random_post["id"]

                            # Формируем полный URL изображения
                            file_url = None
                            if "file_url" in random_post and random_post["file_url"]:
                                file_url = random_post["file_url"]
                                if not file_url.startswith("http"):
                                    file_url = f"https:{file_url}"
                            elif "directory" in random_post and "image" in random_post:
                                directory = random_post["directory"]
                                image = random_post["image"]
                                file_url = f"https://safebooru.org/images/{directory}/{image}"

                            if file_url:
                                logger.info(
                                    f"Найдено изображение (ID: {post_id}), "
                                    f"стр. {random_page}, попытка {attempt + 1}"
                                )
                                return str(file_url), int(post_id)
                            else:
                                logger.debug(f"Нет URL в посте на стр. {random_page}")
                                continue  # Пробуем следующую страницу
                        else:
                            logger.debug(f"HTTP {response.status} на стр. {random_page}")
                            continue  # Пробуем следующую страницу
                except Exception:
                    logger.debug(f"Исключение на стр. {random_page}")
                    continue  # Пробуем следующую страницу

            # Если все попытки исчерпаны
            logger.warning(f"Не удалось найти изображение после {max_page_attempts} попыток")
            return None

    async def post_anime_image(self) -> bool:
        """Получает URL аниме-изображения и публикует его в настроенный канал.

        Логирует результат или ошибки.

        Процесс:
        1. Проверяет существование настроенного канала
        2. Вызывает get_anime_image() для получения URL изображения
        3. Отправляет URL в канал (Discord автоматически отобразит изображение)
        4. Логирует результат операции или возникшие ошибки

        Returns:
            True, если изображение успешно опубликовано, иначе False.
        """
        try:
            # Проверяем существование канала
            if not await self._check_channel_exists():
                return False

            # Получаем объект канала по ID
            channel = self.bot.get_channel(self.channel_id)

            # Получаем URL изображения
            image_data = await self.get_anime_image()

            if image_data:
                image_url, post_id = image_data
                await channel.send(image_url)
                self.post_cache.append(post_id)
                try:
                    import time
                    await AnimeCache.create(post_id=post_id, added_at=int(time.time()))
                except Exception as e:
                    logger.error(f"Ошибка при сохранении поста {post_id} в БД: {e}", exc_info=True)

                logger.info(
                    f"Аниме-изображение (ID: {post_id}) опубликовано в канале {channel.name}. "
                    f"Размер кэша: {len(self.post_cache)}/{self.cache_size}"
                )
                return True
            else:
                logger.error("Не удалось получить новое аниме-изображение для публикации")
                return False

        except Exception as e:
            logger.error(f"Ошибка в post_anime_image: {e}", exc_info=True)
            return False

    # --- Фоновые задачи ---

    @tasks.loop(time=time(hour=10, minute=0))  # Значение по умолчанию, будет изменено в __init__
    async def morning_post(self) -> None:
        """Задача, выполняющаяся ежедневно для утренней публикации."""
        logger.info("Запуск утренней публикации аниме...")
        await self.post_anime_image()

    @tasks.loop(time=time(hour=18, minute=0))  # Значение по умолчанию, будет изменено в __init__
    async def evening_post(self) -> None:
        """Задача, выполняющаяся ежедневно для вечерней публикации."""
        logger.info("Запуск вечерней публикации аниме...")
        await self.post_anime_image()

    @morning_post.before_loop
    async def before_morning_post(self) -> None:
        """Ожидает готовности бота перед первым запуском утренней задачи."""
        await self.bot.wait_until_ready()
        logger.info("Задача morning_post готова к запуску.")

    @evening_post.before_loop
    async def before_evening_post(self) -> None:
        """Ожидает готовности бота перед первым запуском вечерней задачи."""
        await self.bot.wait_until_ready()
        logger.info("Задача evening_post готова к запуску.")

    # --- Команды ---

    @commands.hybrid_command(description="Опубликовать случайное аниме-изображение сейчас")
    @commands.has_permissions(administrator=True)  # Только для администраторов
    @command_error_handler
    async def post_anime(self, ctx: commands.Context) -> None:
        """Команда для ручной публикации случайного аниме-изображения.

        Доступно администраторам. Публикует в настроенный канал.

        Args:
            ctx: Контекст команды.
        """
        # Проверяем существование канала
        if not await self._check_channel_exists():
            await ctx.send(
                "Ошибка: канал для публикации аниме не настроен или не найден.", ephemeral=True
            )
            return

        # Публикуем изображение
        success = await self.post_anime_image()

        if success:
            channel = self.bot.get_channel(self.channel_id)
            await ctx.send(
                f"Аниме-изображение успешно опубликовано в канале #{channel.name}!", ephemeral=True
            )
        else:
            await ctx.send(
                "Не удалось опубликовать аниме-изображение. Проверьте логи для подробностей.",
                ephemeral=True,
            )

    async def _check_channel_exists(self) -> bool:
        """Проверяет существование настроенного канала для публикации.

        Returns:
            True, если канал существует и доступен, иначе False.
        """
        if not self.channel_id:
            logger.error("ID канала для публикации аниме не настроен.")
            return False

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            logger.error(f"Канал с ID {self.channel_id} не найден")
            return False

        return True

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Обрабатывает ошибки, возникающие при выполнении команд в этом коге.

        Args:
            ctx: Контекст команды, где произошла ошибка.
            error: Объект ошибки.
        """
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас нет прав для выполнения этой команды.", ephemeral=True)
        elif isinstance(error, commands.CommandInvokeError):
            logger.error(
                f"Ошибка при выполнении команды: {error.original}", exc_info=error.original
            )
            await ctx.send(f"Произошла ошибка: {error.original}", ephemeral=True)
        else:
            logger.error(f"Необработанная ошибка в команде: {error}", exc_info=error)
            await ctx.send(f"Произошла неизвестная ошибка: {error}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Загружает ког AnimeCog в бота.

    Args:
        bot: Экземпляр бота Discord.
    """
    await bot.add_cog(AnimeCog(bot))
    logger.info("Ког AnimeCog успешно загружен.")
