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

from config import get_settings
from utils.error_handler import get_error_message, safe_send_error

logger = logging.getLogger("bot.handlers.events")

# Какие исключения мы считаем «штатными» для префиксных команд — их не нужно
# валить в лог со стеком, достаточно ответа пользователю.
_KNOWN_PREFIX_ERRORS = (
    commands.MissingRequiredArgument,
    commands.BadArgument,
    commands.MissingPermissions,
    commands.BotMissingPermissions,
    commands.CommandOnCooldown,
    commands.NotOwner,
    commands.MemberNotFound,
    commands.ChannelNotFound,
    commands.RoleNotFound,
)


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
            await self._sync_commands()

        # Установка статуса
        await self.bot.change_presence(activity=discord.Game(name="Делаю милые вещи и пью чай"))
        logger.info("Статус бота установлен.")

    async def _sync_commands(self) -> None:
        """Синхронизирует slash-команды один раз за сессию.

        Если в конфиге задан ``guild_id`` — копирует глобальные команды в эту
        гильдию и синкает точечно (Discord применяет их мгновенно, без часовой
        раскатки). Иначе — глобальный синк (fallback для не настроенного
        ``GUILD_ID``).
        """
        guild_id = get_settings().guild_id
        logger.info("Синхронизация slash-команд...")
        try:
            if guild_id:
                guild = discord.Object(id=guild_id)
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                scope = f"в гильдию {guild_id}"
            else:
                synced = await self.bot.tree.sync()
                scope = "глобально (раскатка до часа; задай GUILD_ID для мгновенного синка)"
            command_names = [cmd.name for cmd in synced]
            logger.info(
                f"Синхронизировано {len(synced)} команд {scope}: {', '.join(command_names)}"
            )
            self._synced = True
        except Exception as e:
            logger.error(f"Не удалось синхронизировать команды: {e}")

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

        Тексты сообщений берём из общего :data:`utils.error_handler.ERROR_MESSAGES`,
        чтобы пользователь видел одинаковые формулировки независимо от того,
        дошёл ли запрос до ``@command_error_handler`` или упал раньше.
        """
        if isinstance(error, commands.CommandNotFound):
            return

        # Неизвестные программные баги логируем со стеком — пользователю
        # уйдёт обобщённое «непредвиденная ошибка» из get_error_message.
        if not any(isinstance(error, etype) for etype in _KNOWN_PREFIX_ERRORS):
            logger.error(
                f"Необработанная ошибка в префиксной команде '{ctx.command}': {error}",
                exc_info=True,
            )

        await safe_send_error(ctx, get_error_message(error))


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког Events к боту.

    Args:
        bot: Экземпляр discord.ext.commands.Bot.
    """
    await bot.add_cog(Events(bot))
    logger.info("Ког Events добавлен к боту.")
