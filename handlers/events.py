"""Ког для обработки основных событий Discord и управления жизненным циклом бота."""

import asyncio
import logging

import discord
from discord.ext import commands  # Явно перезаписываем импорт

# Определяем logger до его использования
logger = logging.getLogger("bot.handlers.events")

# Импорты для музыки
try:
    # Импортируем MusicPlayer из правильного модуля
    from utils.music import MusicPlayer

    # Определяем функции для работы с музыкой
    async def cleanup_player(player: MusicPlayer, guild_name: str) -> None:
        """Очищает плеер после отключения.

        Args:
            player: Экземпляр музыкального плеера.
            guild_name: Название гильдии, для которой очищается плеер.
        """
        if player:
            await player.cleanup(clear_queue=True)
            logger.info(f"Плеер очищен для гильдии {guild_name}")

    async def auto_disconnect(
        player: MusicPlayer, guild: discord.Guild, voice_channel: discord.VoiceChannel
    ) -> None:
        """Автоматически отключает бота после периода неактивности.

        Args:
            player: Экземпляр музыкального плеера.
            guild: Гильдия, в которой находится бот.
            voice_channel: Голосовой канал, из которого нужно отключиться.
        """
        logger.info(f"Запущено автоотключение для {guild.name} из канала {voice_channel.name}")
        await asyncio.sleep(180)  # 3 минуты ожидания

        # Проверяем, что бот все еще в том же канале и канал пуст
        voice_client = guild.voice_client
        if voice_client and voice_client.channel == voice_channel:
            if len(voice_client.channel.members) == 1:  # Только бот в канале
                logger.info(f"Автоотключение из {voice_channel.name} после периода неактивности")
                await player.disconnect()

except ImportError:
    # Используем # type: ignore для обхода проблем с типизацией в случае ImportError
    cleanup_player = None  # type: ignore
    auto_disconnect = None  # type: ignore
    MusicPlayer = None  # type: ignore  # Определяем как None, если импорт не удался
    logger.warning("Модули для работы с музыкой не найдены")


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

    # Возвращаем старую логику on_voice_state_update
    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Событие: вызывается при изменении голосового состояния участника.

        Используется для автоматического отключения музыкального бота.

        Args:
            member: Участник, чье голосовое состояние изменилось.
            before: Голосовое состояние до изменения.
            after: Голосовое состояние после изменения.
        """
        try:
            if before.channel == after.channel:
                return  # Игнорируем смену состояния без смены канала

            # Получаем плеер из кога Music (предполагаем, что он там один)
            music_cog = self.bot.get_cog("Music")
            player = getattr(music_cog, "player", None) if music_cog else None

            # Проверяем, доступны ли функции и плеер
            if cleanup_player is None or auto_disconnect is None or MusicPlayer is None:
                # logger.warning(
                #     "Функции cleanup_player/auto_disconnect или класс MusicPlayer недоступны."
                # ) # Убрано, т.к. может спамить
                return
            if not isinstance(player, MusicPlayer):  # Проверяем, что плеер действительно есть
                # logger.warning("Экземпляр плеера не найден в коге Music.") # Убрано
                return

            # Если сам бот был отключен от канала
            if member.id == self.bot.user.id and before.channel and not after.channel:
                logger.info(f"Бот был отключен от канала {before.channel.name}")
                # Передаем плеер и имя гильдии
                await cleanup_player(player, member.guild.name)
                return

            # Если пользователь (не бот) покинул голосовой канал, в котором находится бот
            if before.channel and not member.bot:
                voice_client = member.guild.voice_client
                if voice_client and voice_client.channel == before.channel:
                    await asyncio.sleep(1)  # Даем время на обновление списка участников
                    # Перепроверяем voice_client и количество участников
                    voice_client = member.guild.voice_client
                    if (
                        voice_client and len(voice_client.channel.members) == 1
                    ):  # Если остался только бот
                        logger.info(
                            f"Последний пользователь покинул канал {before.channel.name}, "
                            "запускаем автоотключение..."
                        )
                        # Передаем плеер, гильдию и голосовой канал
                        asyncio.create_task(auto_disconnect(player, member.guild, before.channel))
        except Exception as e:
            logger.error(f"Ошибка в on_voice_state_update: {e}", exc_info=True)

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
