"""Ког для обработки входящих сообщений пользователей и их маршрутизации."""

import logging
import time

import discord
from discord.ext import commands

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

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога.

        Выполняет необходимые действия для корректного завершения работы кога.
        """
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
        # Игнорируем сообщения от ботов, сообщения вне серверов (в ЛС) и команды
        # Получаем префиксы для текущего сообщения
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

        if message.author.bot or not message.guild or is_command:
            return

        author_id = message.author.id
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

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """
        Обработчик ошибок для команд этого кога.

        Args:
            ctx: Контекст команды, в которой произошла ошибка.
            error: Объект ошибки.
        """
        logger.error(f"Ошибка в команде {ctx.command}: {error}", exc_info=True)
        await ctx.send(f"❌ Произошла ошибка при выполнении команды: {error}")


async def setup(bot: commands.Bot) -> None:
    """
    Добавляет ког MessageHandler к боту.

    Args:
        bot: Экземпляр discord.ext.commands.Bot.
    """
    await bot.add_cog(MessageHandler(bot))
    logger.info("Ког MessageHandler добавлен к боту.")
