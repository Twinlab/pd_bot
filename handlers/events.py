"""Ког для обработки основных событий Discord и управления жизненным циклом бота.

Музыкальная логика (авто-дисконнект из пустого канала, очистка плеера) больше
**не** живёт в этом файле — её взял на себя ``cogs/music.py`` через слушатели
``on_wavelink_inactive_player`` и ``on_voice_state_update``. Здесь остался
только общий жизненный цикл бота: ``on_ready``, прощание с покинувшими сервер
участниками и глобальный обработчик ошибок префиксных команд.
"""

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.handlers.events")


class Events(commands.Cog):
    """Ког для обработки основных событий Discord.

    Обрабатывает события жизненного цикла бота, такие как готовность к работе,
    присоединение/отключение участников, изменения голосовых состояний и ошибки команд.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког для обработки событий.

        Args:
            bot: Экземпляр бота Discord.
        """
        self.bot: commands.Bot = bot
        self._synced: bool = False

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога.

        Выполняет необходимые действия для корректного завершения работы кога.
        """
        logger.info(f"Ког {self.__class__.__name__} выгружается")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Событие: бот готов к работе.

        Вызывается, когда бот успешно подключился к Discord и готов обрабатывать события.
        Выполняет синхронизацию slash-команд и устанавливает статус бота.
        """
        logger.info(f"Бот {self.bot.user.name} (ID: {self.bot.user.id}) готов к работе.")
        logger.info(f"Версия discord.py: {discord.__version__}")

        # Синхронизация slash-команд (только один раз, on_ready вызывается при каждом reconnect)
        if not self._synced:
            logger.info("Синхронизация slash-команд...")
            try:
                synced = await self.bot.tree.sync()
                command_names = [cmd.name for cmd in synced]
                logger.info(f"Синхронизировано {len(synced)} команд: {', '.join(command_names)}")
                self._synced = True
            except Exception as e:
                logger.error(f"Не удалось синхронизировать команды: {e}")

        # Установка статуса
        await self.bot.change_presence(activity=discord.Game(name="Делаю милые вещи и пью чай"))
        logger.info("Статус бота установлен.")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Событие: участник покинул сервер.

        Отправляет сообщение в канал #general или другой доступный канал,
        уведомляя о выходе участника с сервера.

        Args:
            member: Участник, который покинул сервер.
        """
        try:
            channel = discord.utils.get(member.guild.text_channels, name="general")
            if not channel:
                logger.debug(
                    f"Канал #general не найден на сервере {member.guild.name}, ищем другой канал..."
                )
                channels = [
                    c
                    for c in member.guild.text_channels
                    if c.permissions_for(member.guild.me).send_messages
                ]
                if channels:
                    channel = channels[0]

            if channel:
                await channel.send(f"**{member.name}** ббак")
        except Exception as e:
            logger.error(f"Ошибка в on_member_remove: {e}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Глобальный обработчик ошибок для префиксных команд.

        Args:
            ctx: Контекст команды, в которой произошла ошибка.
            error: Объект ошибки.
        """
        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingRequiredArgument):
            message = f"Отсутствует аргумент: `{error.param.name}`"
        elif isinstance(error, commands.BadArgument):
            message = "Неверный аргумент команды"
        elif isinstance(error, commands.MissingPermissions):
            message = "Нет прав для выполнения команды"
        elif isinstance(error, commands.BotMissingPermissions):
            message = f"У бота нет прав: {', '.join(error.missing_permissions)}"
        elif isinstance(error, commands.CommandOnCooldown):
            message = f"Перезарядка. Попробуйте через {error.retry_after:.1f} сек."
        elif isinstance(error, commands.NotOwner):
            message = "Команда только для владельца бота"
        else:
            logger.error(
                f"Необработанная ошибка в префиксной команде '{ctx.command}': {error}",
                exc_info=True,
            )
            message = f"Произошла ошибка: {error}"
        await self._send_error(ctx, message)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Обработчик ошибок для команд этого кога.

        Args:
            ctx: Контекст команды, в которой произошла ошибка.
            error: Объект ошибки.
        """
        # Делегируем обработку глобальному обработчику
        await self.on_command_error(ctx, error)

    async def _send_error(self, ctx: commands.Context, message: str) -> None:
        """Вспомогательный метод для отправки сообщения об ошибке (для префиксных команд).

        Args:
            ctx: Контекст команды.
            message: Сообщение об ошибке для отправки.
        """
        try:
            await ctx.send(f"❌ {message}")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение об ошибке пользователю: {e}")


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког Events к боту.

    Args:
        bot: Экземпляр discord.ext.commands.Bot.
    """
    await bot.add_cog(Events(bot))
    logger.info("Ког Events добавлен к боту.")
