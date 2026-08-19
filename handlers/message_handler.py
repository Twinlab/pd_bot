"""Ког для обработки входящих сообщений пользователей и их маршрутизации."""

import asyncio
import logging
import time

import discord
from discord.ext import commands

from utils.user_stats_data_manager import UserStatsDataManager

logger = logging.getLogger("bot.handlers.message_handler")


class MessageHandler(commands.Cog):
    """
    Ког для обработки входящих сообщений пользователей.

    Игнорирует ботов, личные сообщения и команды.
    Применяет кулдаун для предотвращения спама реакциями.
    Вызывает `utils.message_utils.handle_message` для основной логики.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        Инициализирует ког и словарь для кулдаунов.

        Args:
            bot: Экземпляр бота Discord.
        """
        self.bot: commands.Bot = bot
        # Словарь для отслеживания времени последней обработки сообщения от пользователя
        # {user_id: timestamp}
        self.cooldowns: dict[int, float] = {}
        self.stats_manager: UserStatsDataManager = UserStatsDataManager()
        self._stats_tasks: set[asyncio.Task[None]] = set()

    def _on_stats_task_done(self, task: asyncio.Task[None]) -> None:
        """Удаляет завершённую задачу счётчика и забирает возможное исключение."""
        self._stats_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Ошибка фоновой записи счётчика сообщений")

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога.

        Выполняет необходимые действия для корректного завершения работы кога.
        """
        if self._stats_tasks:
            await asyncio.gather(*tuple(self._stats_tasks), return_exceptions=True)
        logger.info(f"Ког {self.__class__.__name__} выгружается")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Событие: вызывается при получении нового сообщения.

        Фильтрует сообщения и вызывает обработчик `handle_message`.
        Применяет кулдаун для предотвращения спама реакциями.

        Args:
            message: Объект сообщения Discord.
        """
        if message.author.bot or message.guild is None:
            return

        prefixes = await self.bot.get_prefix(message)
        # Если prefixes это строка, оборачиваем в список для единообразия
        if isinstance(prefixes, str):
            prefixes = [prefixes]

        is_command = False
        if prefixes:  # Проверяем, что prefixes не пустой
            for p in prefixes:
                if message.content.startswith(p):
                    is_command = True
                    break

        if is_command:
            return

        author_id = message.author.id

        # Счётчик сообщений для wrapped считаем БЕЗ анти-спам кулдауна (иначе
        # потеряем большинство сообщений активных болтунов). Запускаем фоном,
        # чтобы запись в БД не тормозила обработку сообщения.
        stats_task = asyncio.create_task(
            self.stats_manager.add_message(author_id),
            name=f"message-stats-{author_id}",
        )
        self._stats_tasks.add(stats_task)
        stats_task.add_done_callback(self._on_stats_task_done)

        current_time = time.monotonic()

        if author_id in self.cooldowns and current_time - self.cooldowns[author_id] < 2:
            return

        self.cooldowns[author_id] = current_time

        if len(self.cooldowns) > 200:
            cutoff = current_time - 10
            self.cooldowns = {uid: ts for uid, ts in self.cooldowns.items() if ts > cutoff}

        # Вызываем основную логику обработки сообщения из utils
        try:
            # Импорт внутри метода для избежания потенциальных циклических зависимостей при запуске
            from utils.message_utils import handle_message

            await handle_message(message)
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)


async def setup(bot: commands.Bot) -> None:
    """
    Добавляет ког MessageHandler к боту.

    Args:
        bot: Экземпляр discord.ext.commands.Bot.
    """
    await bot.add_cog(MessageHandler(bot))
    logger.info("Ког MessageHandler добавлен к боту.")
