"""Ког для автоматической и ручной публикации SFW аниме-изображений.

Этот модуль предоставляет функциональность для автоматической публикации
аниме-изображений в заданный канал Discord по расписанию (утром и вечером),
а также команду для ручной публикации изображений администраторами.
Изображения получаются с сайта safebooru.org через их API.
"""

import logging
import random
from datetime import time
from typing import Any, Optional

import aiohttp
from discord.ext import commands, tasks

from config import get_settings
from utils.error_handler import command_error_handler

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
        self.channel_id: Optional[int] = settings.channels.anime

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

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога, останавливает фоновые задачи."""
        logger.info("Остановка задач публикации аниме...")
        self.morning_post.cancel()
        self.evening_post.cancel()

    async def get_anime_image(self) -> Optional[str]:
        """Асинхронно получает URL случайного SFW аниме-изображения с safebooru.org.

        Использует API safebooru.org для поиска изображений по настроенным тегам.
        Случайным образом выбирает несколько тегов из конфигурации и выполняет поиск.
        Также добавляет исключенные теги с префиксом "-".

        Если основной запрос не дает результатов, делает fallback запрос только с тегом "1girl".

        Returns:
            URL изображения в виде строки или None в случае ошибки.
        """
        settings = get_settings()

        # Сначала пробуем основной запрос с выбранными тегами
        result = await self._try_get_image_with_tags(settings)
        if result:
            return result

        # Если основной запрос не дал результатов, пробуем fallback с только "1girl"
        logger.info("Основной запрос не дал результатов, пробуем fallback с тегом '1girl'")
        return await self._try_get_image_fallback(settings)

    async def _try_get_image_with_tags(self, settings: Any) -> Optional[str]:
        """Пробует получить изображение с выбранными тегами."""
        # Выбираем случайные теги из настроек
        # (не больше max_tags_per_request - 1, т.к. добавим 1girl)
        available_tags = [
            tag for tag in settings.anime.tags if tag != "1girl"
        ]  # Исключаем 1girl из выбора
        max_tags = min(
            settings.anime.max_tags_per_request - 1, len(available_tags)
        )  # -1 для обязательного 1girl

        if max_tags > 0 and available_tags:
            selected_tags = random.sample(available_tags, random.randint(1, max_tags))
        else:
            selected_tags = []

        # Добавляем обязательный тег "1girl"
        all_selected_tags = ["1girl"] + selected_tags

        # Добавляем исключенные теги с префиксом "-"
        excluded_tags = [f"-{tag}" for tag in settings.anime.excluded_tags]

        # Объединяем все теги
        all_tags = all_selected_tags + excluded_tags + [f"rating:{settings.anime.rating}"]

        return await self._make_api_request(all_tags, all_selected_tags, settings)

    async def _try_get_image_fallback(self, settings: Any) -> Optional[str]:
        """Fallback запрос только с тегом '1girl' и исключениями."""
        # Только обязательные теги: 1girl + исключения + рейтинг
        selected_tags = ["1girl"]
        excluded_tags = [f"-{tag}" for tag in settings.anime.excluded_tags]
        all_tags = selected_tags + excluded_tags + [f"rating:{settings.anime.rating}"]

        return await self._make_api_request(all_tags, selected_tags, settings)

    async def _make_api_request(
        self, all_tags: list[str], selected_tags: list[str], settings: Any
    ) -> Optional[str]:
        """Выполняет запрос к API safebooru.org."""
        # Формируем параметры запроса для safebooru API
        params = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": "1",
            "limit": "100",  # Получаем больше результатов для лучшей случайности
            "tags": " ".join(all_tags),
        }

        # URL API safebooru.org
        api_url = "https://safebooru.org/index.php"

        async with aiohttp.ClientSession() as session:
            try:
                # Выполняем запрос к API
                async with session.get(api_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Проверяем, что получили результаты
                        if not data or not isinstance(data, list) or len(data) == 0:
                            logger.warning(f"Нет изображений для тегов: {selected_tags}")
                            return None

                        # Выбираем случайное изображение из результатов
                        random_post = random.choice(data)

                        # Формируем полный URL изображения
                        if "file_url" in random_post and random_post["file_url"]:
                            # Если есть прямая ссылка на файл
                            file_url = random_post["file_url"]
                            if not file_url.startswith("http"):
                                file_url = f"https:{file_url}"
                            logger.info(
                                f"Найдено изображение с тегами: {selected_tags}, "
                                f"исключены: {settings.anime.excluded_tags}"
                            )
                            return str(file_url)
                        elif "directory" in random_post and "image" in random_post:
                            # Формируем URL из directory и image
                            directory = random_post["directory"]
                            image = random_post["image"]
                            file_url = f"https://safebooru.org/images/{directory}/{image}"
                            logger.info(
                                f"Найдено изображение с тегами: {selected_tags}, "
                                f"исключены: {settings.anime.excluded_tags}"
                            )
                            return str(file_url)
                        else:
                            logger.error(
                                f"Не удалось извлечь URL изображения из ответа: {random_post}"
                            )
                            return None
                    else:
                        logger.error(f"Ошибка при запросе к safebooru API: {response.status}")
                        return None
            except Exception as e:
                logger.error(f"Ошибка при получении аниме-изображения: {e}", exc_info=True)
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
            image_url = await self.get_anime_image()

            if image_url:
                # Отправляем URL в канал (Discord автоматически отобразит изображение)
                await channel.send(image_url)
                logger.info(f"Аниме-изображение опубликовано в канале {channel.name}")
                return True
            else:
                logger.error("Не удалось получить аниме-изображение для публикации")
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
