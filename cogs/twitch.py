"""Ког для отслеживания стримов на Twitch и отправки уведомлений в Discord каналы.

Этот модуль отвечает за:
- Добавление и удаление Twitch-стримеров для отслеживания.
- Периодическую проверку статуса отслеживаемых стримов через Twitch API.
- Отправку уведомлений в заданные Discord каналы при начале стрима.
- Кэширование информации о стримерах для оптимизации.
- Управление списком отслеживаемых стримеров.
"""

import asyncio
import datetime
import logging
from datetime import UTC
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import get_settings
from utils.error_handler import handle_app_command_error, safe_send_error
from utils.twitch_api import TwitchAPI
from utils.twitch_data_manager import TwitchDataManager
from utils.ui import image_card

logger = logging.getLogger("bot.cogs.twitch")

TWITCH_ICON_URL = "https://static.twitchcdn.net/assets/favicon-32-d6025c14e900565d6177.png"


def _build_stream_view(
    stream_data: dict[str, Any], username: str, accent: int
) -> discord.ui.LayoutView:
    """Собирает CV2-карточку уведомления о начале стрима.

    Превью идёт через ``MediaGallery``, ссылка на канал — кликабельным заголовком
    и кнопкой «Смотреть». Раньше это был ``discord.Embed`` с author/image/fields.

    Args:
        stream_data: Данные стрима из Twitch API (title, user_name, game_name и т.д.).
        username: Логин стримера для ссылок на ``twitch.tv``.
        accent: Цвет акцентной полосы контейнера (int).

    Returns:
        Готовый ``LayoutView`` с карточкой стрима.
    """
    stream_url = f"https://twitch.tv/{username}"
    title = stream_data["title"] or "Стрим"
    thumbnail_url = (
        stream_data["thumbnail_url"].replace("{width}", "1280").replace("{height}", "720")
    )

    return image_card(
        media=thumbnail_url,
        accent=accent,
        text_above=[
            f"🔴 **{stream_data['user_name']}** начал(а) стрим!",
            f"### [{title}]({stream_url})",
        ],
        text_below=[
            f"**Категория:** {stream_data['game_name'] or 'Не указана'}\n"
            f"**Зрители:** {stream_data['viewer_count']}"
        ],
        links=[("Смотреть на Twitch", stream_url)],
        timeout=None,
    )


class TwitchCog(commands.Cog):
    """Ког для отслеживания стримов на Twitch.

    Предоставляет функциональность для отслеживания Twitch-стримеров и отправки
    уведомлений в Discord каналы при начале стрима. Включает команды для добавления,
    удаления и просмотра списка отслеживаемых стримеров.

    Attributes:
        bot: Экземпляр бота Discord
        data_manager: Менеджер данных для работы с БД
        client_id: Client ID приложения Twitch
        client_secret: Client Secret приложения Twitch
        twitch_api: Клиент для работы с Twitch API
        streamers_cache: Кеш информации о стримерах
        check_interval: Интервал проверки статуса стримов в секундах
        first_run: Флаг первого запуска проверки стримов
    """

    bot: commands.Bot
    data_manager: TwitchDataManager
    client_id: str
    client_secret: str
    twitch_api: TwitchAPI | None
    streamers_cache: dict[str, dict[str, Any]]
    check_interval: int
    first_run: bool

    def __init__(self, bot: commands.Bot):
        """Инициализирует ког TwitchCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot = bot
        self.data_manager = TwitchDataManager()

        # Получаем Twitch API ключи из конфигурации
        self.client_id = bot.settings.twitch_client_id or ""
        self.client_secret = bot.settings.twitch_client_secret or ""

        # Проверяем наличие ключей и что они не пустые
        if not self.client_id.strip() or not self.client_secret.strip():
            logger.warning(self.bot.settings.messages.errors["twitch_api_not_configured"])
            self.twitch_api = None
        else:
            self.twitch_api = TwitchAPI(self.client_id, self.client_secret)

        # Кеш для хранения информации о стримерах
        self.streamers_cache: dict[
            str, dict[str, Any]
        ] = {}  # {username: {'user_id': str, 'is_live': bool, 'stream_data': dict[str, Any] | None}}

        # Получаем настройки из конфигурации
        settings = get_settings()

        # Интервал проверки стримов (в секундах)
        self.check_interval = settings.twitch.check_interval

        # Флаг для отслеживания первого запуска
        self.first_run = True

    async def cog_load(self) -> None:
        """Вызывается при загрузке кога.

        Инициализирует Twitch API и запускает фоновую задачу проверки статуса.
        """
        # Инициализируем Twitch API
        if self.twitch_api:
            await self.twitch_api.initialize()
            # Изменяем интервал задачи на значение из конфигурации
            self.check_streams.change_interval(seconds=self.check_interval)
            # Запускаем фоновую задачу для проверки стримов
            self.check_streams.start()
        else:
            logger.warning(
                "Twitch API не инициализирован. Фоновая задача проверки стримов не запущена."
            )

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога.

        Останавливает фоновую задачу проверки стримов и закрывает соединение с Twitch API.
        """
        logger.info("Выгрузка кога TwitchCog")

        # Останавливаем фоновую задачу
        if self.check_streams.is_running():
            self.check_streams.cancel()

        # Закрываем Twitch API
        if self.twitch_api:
            await self.twitch_api.close()

    @tasks.loop(seconds=60)  # Будет изменено динамически
    async def check_streams(self) -> None:
        """Фоновая задача для проверки статуса стримов."""
        try:
            # При первом запуске делаем паузу, чтобы бот успел полностью загрузиться
            if self.first_run:
                self.first_run = False
                settings = get_settings()
                logger.info(
                    f"Первый запуск проверки стримов, "
                    f"ожидаем {settings.twitch.startup_delay} секунд..."
                )
                await asyncio.sleep(settings.twitch.startup_delay)

            logger.debug("Начало проверки статуса стримов")

            guild = self.bot.guilds[0] if self.bot.guilds else None
            if guild is None:
                logger.error("Настроенная гильдия не найдена в кеше Discord")
                return

            streamers = await self.data_manager.get_streamers(guild.id)
            if not streamers:
                logger.debug("Нет отслеживаемых стримеров")
                return

            streamers_by_username = {
                streamer["twitch_username"]: streamer for streamer in streamers
            }

            # Получаем информацию о пользователях Twitch
            usernames = list(streamers_by_username.keys())
            if self.twitch_api is None:
                logger.error("Twitch API не инициализирован")
                return
            users = await self.twitch_api.get_users(usernames)

            # Создаем словарь {username: user_id}
            user_ids_by_username = {}
            for user in users:
                username = user["login"].lower()
                user_ids_by_username[username] = user["id"]

                # Обновляем Twitch ID в базе данных, если он отсутствует
                streamer = streamers_by_username.get(username)
                if streamer is not None and not streamer["twitch_id"]:
                    await self.data_manager.update_twitch_id(username, guild.id, user["id"])

            # Получаем информацию о текущих стримах
            user_ids = [user["id"] for user in users]
            streams = await self.twitch_api.get_streams(user_ids)

            # Создаем словарь {user_id: stream_data}
            streams_by_user_id = {stream["user_id"]: stream for stream in streams}

            # Обновляем статус стримеров и отправляем уведомления
            for username, streamer_info in streamers_by_username.items():
                # Пропускаем стримеров, которых нет в ответе API
                if username not in user_ids_by_username:
                    logger.warning(f"Стример {username} не найден в Twitch API")
                    continue

                user_id = user_ids_by_username[username]
                is_live = user_id in streams_by_user_id
                stream_data = streams_by_user_id.get(user_id)
                stream_id = stream_data["id"] if stream_data else None

                if username not in self.streamers_cache:
                    self.streamers_cache[username] = {
                        "user_id": user_id,
                        "is_live": bool(streamer_info["is_live"]),
                        "last_stream_id": streamer_info["last_stream_id"],
                        "stream_data": None,
                    }

                cached = self.streamers_cache[username]
                was_live = bool(cached["is_live"])
                previous_stream_id = cached.get("last_stream_id")
                is_new_stream = is_live and stream_id != previous_stream_id

                if is_new_stream:
                    logger.info(
                        f"ОБНАРУЖЕН НОВЫЙ СТРИМ: Стример {username} начал стрим: "
                        f"{stream_data['title']}"
                        if stream_data
                        else f"ОБНАРУЖЕН НОВЫЙ СТРИМ: Стример {username} — нет данных о стриме"
                    )

                    channel_id = streamer_info["channel_id"]
                    logger.info(f"Отправка уведомления о стриме {username} в канал {channel_id}")
                    notification_sent = await self.send_stream_notification(
                        guild.id,
                        channel_id,
                        username,
                        stream_data if stream_data else {},
                    )
                    if not notification_sent:
                        logger.warning(
                            "Уведомление о стриме %s не отправлено; повторим на следующей проверке",
                            username,
                        )
                        continue

                    await self.data_manager.update_streamer_status(
                        username, guild.id, True, stream_id
                    )
                    await self.data_manager.update_notification_time(username, guild.id, stream_id)
                    cached["is_live"] = True
                    cached["last_stream_id"] = stream_id

                elif is_live:
                    if not was_live:
                        await self.data_manager.update_streamer_status(
                            username,
                            guild.id,
                            True,
                            stream_id,
                        )
                    cached["is_live"] = True

                elif not is_live and was_live:
                    logger.info(f"Стример {username} закончил стрим")
                    await self.data_manager.update_streamer_status(username, guild.id, False)
                    cached["is_live"] = False

                cached["user_id"] = user_id
                cached["stream_data"] = stream_data

            logger.debug("Проверка статуса стримов завершена")

        except Exception as e:
            logger.error(f"Ошибка при проверке статуса стримов: {e}", exc_info=True)

    @check_streams.before_loop
    async def before_check_streams(self) -> None:
        """Выполняется перед запуском фоновой задачи.

        Ожидает готовности бота перед началом проверки стримов,
        чтобы убедиться, что все системы инициализированы.
        """
        await self.bot.wait_until_ready()
        logger.info("Бот готов, запускаем проверку стримов")

    async def send_stream_notification(
        self, guild_id: int, channel_id: int, username: str, stream_data: dict[str, Any]
    ) -> bool:
        """Отправляет уведомление о начале стрима в указанный канал.

        Args:
            guild_id: ID сервера Discord
            channel_id: ID канала для отправки уведомления
            username: Имя пользователя Twitch
            stream_data: Данные о стриме

        Returns:
            ``True``, если сообщение подтверждённо отправлено.
        """
        try:
            logger.info(f"НАЧАЛО: Отправка уведомления о стриме {username} в канал {channel_id}")

            # Проверяем наличие необходимых ключей в stream_data
            required_keys = ["title", "user_name", "thumbnail_url", "game_name", "viewer_count"]
            if not stream_data or not all(key in stream_data for key in required_keys):
                logger.error(
                    f"Неполные данные стрима для {username}: "
                    f"отсутствуют ключи {set(required_keys) - set(stream_data or {})}"
                )
                return False

            # Проверяем, что бот готов
            if not self.bot.is_ready():
                logger.error(f"Бот не готов при попытке отправить уведомление о стриме {username}")
                return False

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                logger.error("Гильдия с ID %s не найдена в кеше Discord", guild_id)
                return False
            logger.info(f"Используем сервер: {guild.name} (ID: {guild.id})")

            # Получаем объект канала
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                logger.error(f"Не найден текстовый канал с ID {channel_id} на сервере {guild.name}")

                # Пробуем найти канал по умолчанию
                settings = get_settings()
                default_channel_id = settings.channels.twitch
                default_channel = guild.get_channel(default_channel_id)
                if isinstance(default_channel, discord.TextChannel):
                    logger.info(
                        f"Используем канал по умолчанию {default_channel.name} "
                        f"({default_channel_id})"
                    )
                    channel = default_channel
                else:
                    logger.error(
                        f"Канал по умолчанию {default_channel_id} не найден или не TextChannel"
                    )
                    return False

            settings = get_settings()
            accent = int(settings.twitch.embed_color.replace("#", ""), 16)

            permissions = channel.permissions_for(guild.me)
            if not permissions.send_messages:
                logger.error(
                    f"У бота нет прав на отправку сообщений в канал {channel.name} "
                    f"({channel.id}) на сервере {guild.name}"
                )
                return False

            try:
                if permissions.embed_links:
                    logger.info(f"Отправка CV2-карточки стрима в канал {channel.name}")
                    view = _build_stream_view(stream_data, username, accent)
                    message = await channel.send(view=view)
                    logger.info(f"Сообщение успешно отправлено: {message.id}")
                else:
                    logger.info(f"Отправка текстового сообщения в канал {channel.name}")
                    message = await channel.send(
                        content=(
                            f"**{stream_data['user_name']}** "
                            f"начал(а) стрим на Twitch!\n"
                            f"Название: {stream_data['title']}\n"
                            f"Ссылка: https://twitch.tv/{username}"
                        )
                    )
                    logger.info(f"Сообщение успешно отправлено: {message.id}")

                logger.info(
                    f"УСПЕХ: Отправлено уведомление о стриме {username} на сервер {guild.name} "
                    f"в канал {channel.name}"
                )
                return True
            except Exception as e:
                logger.error(
                    f"Ошибка при отправке сообщения в канал {channel.name}: {e}", exc_info=True
                )
                return False

        except discord.Forbidden:
            logger.error(
                f"Недостаточно прав для отправки уведомления в канал {channel_id} "
                f"на сервере {guild_id}"
            )
            return False
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о стриме {username}: {e}", exc_info=True)
            return False

    @app_commands.command(
        name="twitch_add", description="Добавляет Twitch-стримера для отслеживания"
    )
    @app_commands.describe(
        twitch_username="Имя пользователя Twitch (без учета регистра)",
        channel="Канал для отправки уведомлений (по умолчанию - текущий канал)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def twitch_add(
        self,
        interaction: discord.Interaction,
        twitch_username: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Добавляет Twitch-стримера для отслеживания.

        Args:
            interaction: Объект взаимодействия Discord
            twitch_username: Имя пользователя Twitch
            channel: Канал для отправки уведомлений (по умолчанию - текущий канал)
        """
        # Проверяем, инициализирован ли Twitch API
        if not self.twitch_api:
            settings = get_settings()
            await safe_send_error(
                interaction, settings.messages.errors["twitch_api_not_configured"]
            )
            return

        # Определяем канал для уведомлений
        settings = get_settings()
        default_channel_id = settings.channels.twitch
        if channel:
            notification_channel = channel
        else:
            # Пытаемся найти канал по умолчанию
            default_channel = (
                interaction.guild.get_channel(default_channel_id) if interaction.guild else None
            )
            if isinstance(default_channel, discord.TextChannel):
                notification_channel = default_channel
                logger.info(
                    f"Используется канал по умолчанию {default_channel.name} ({default_channel_id})"
                )
            else:
                # interaction.channel может быть GuildChannel, Thread, PrivateChannel
                # Нам нужен TextChannel или его подклассы для отправки сообщений
                if isinstance(interaction.channel, discord.TextChannel):
                    notification_channel = interaction.channel
                else:
                    # Если текущий канал не текстовый, пытаемся найти канал по умолчанию
                    # или логируем ошибку и не продолжаем
                    logger.warning(
                        f"Текущий канал взаимодействия не текстовый ({type(interaction.channel)}). "
                        f"Канал по умолчанию {default_channel_id} не найден/не текстовый."
                    )
                    # Отправляем сообщение об ошибке пользователю
                    msg = (
                        "Не удалось определить подходящий текстовый канал для уведомлений. "
                        "Укажите канал явно или убедитесь, что команда "
                        "вызывается из текстового канала."
                    )
                    await safe_send_error(interaction, msg)
                    return
                logger.warning(
                    f"Канал по умолчанию {default_channel_id} не найден или не TextChannel, "
                    f"используется текущий канал {notification_channel.name}"
                )

        # Проверяем, существует ли пользователь Twitch
        user = await self.twitch_api.get_user_by_username(twitch_username)
        if not user:
            await safe_send_error(
                interaction, f"Пользователь Twitch с именем **{twitch_username}** не найден."
            )
            return

        # Добавляем стримера в базу данных
        if interaction.guild_id is None:
            await safe_send_error(interaction, "Ошибка: не удалось определить ID сервера.")
            return
        if isinstance(notification_channel, discord.TextChannel):
            channel_id = notification_channel.id
        else:
            channel_id = 0  # или None, если поддерживается
            logger.warning(
                "Канал для уведомлений не является TextChannel, используется channel_id=0"
            )
        success = await self.data_manager.add_streamer(
            interaction.guild_id, channel_id, user["login"], user["id"]
        )

        if success:
            # Добавляем стримера в кеш
            self.streamers_cache[user["login"].lower()] = {
                "user_id": user["id"],
                "is_live": False,
                "stream_data": None,
            }

            # Проверяем, ведет ли стример стрим в данный момент
            is_live, stream_data = await self.twitch_api.is_user_live(user["id"])
            if is_live and stream_data is not None:
                stream_data_cache = self.streamers_cache[user["login"].lower()]
                stream_data_cache["stream_data"] = stream_data

                logger.info(f"Стример {user['login']} уже в сети, отправляем уведомление")
                notification_sent = await self.send_stream_notification(
                    interaction.guild_id,
                    channel_id,
                    user["login"],
                    stream_data,
                )

                if notification_sent:
                    await self.data_manager.update_streamer_status(
                        user["login"].lower(),
                        interaction.guild_id,
                        True,
                        stream_data["id"],
                    )
                    await self.data_manager.update_notification_time(
                        user["login"].lower(), interaction.guild_id, stream_data["id"]
                    )
                    stream_data_cache["is_live"] = True
                    stream_data_cache["last_stream_id"] = stream_data["id"]

                mention = (
                    notification_channel.mention
                    if isinstance(notification_channel, discord.TextChannel)
                    else str(notification_channel)
                )
                delivery_status = (
                    "Уведомление отправлено в канал."
                    if notification_sent
                    else "Уведомление пока не отправлено; бот повторит попытку при проверке."
                )
                await interaction.response.send_message(
                    (
                        f"Стример **{user['display_name']}** добавлен для отслеживания в канале "
                        f"{mention}.\n"
                        f"Стример сейчас в сети! Стрим: **{stream_data['title']}**\n"
                        f"{delivery_status}"
                    ),
                    ephemeral=True,
                )
            else:
                mention = (
                    notification_channel.mention
                    if isinstance(notification_channel, discord.TextChannel)
                    else str(notification_channel)
                )
                await interaction.response.send_message(
                    (
                        f"Стример **{user['display_name']}** добавлен для отслеживания в канале "
                        f"{mention}."
                    ),
                    ephemeral=True,
                )

            if interaction.guild is not None:
                logger.info(
                    f"Добавлен стример {user['login']} для сервера {interaction.guild.name}"
                )
        else:
            await safe_send_error(
                interaction,
                f"Не удалось добавить стримера **{twitch_username}**. "
                "Возможно, он уже отслеживается.",
            )

    @app_commands.command(
        name="twitch_remove", description="Удаляет Twitch-стримера из отслеживаемых"
    )
    @app_commands.describe(twitch_username="Имя пользователя Twitch (без учета регистра)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def twitch_remove(self, interaction: discord.Interaction, twitch_username: str) -> None:
        """Удаляет Twitch-стримера из отслеживаемых.

        Args:
            interaction: Объект взаимодействия Discord
            twitch_username: Имя пользователя Twitch
        """
        # Удаляем стримера из базы данных
        if interaction.guild_id is None:
            await safe_send_error(interaction, "Ошибка: не удалось определить ID сервера.")
            return
        success = await self.data_manager.remove_streamer(interaction.guild_id, twitch_username)

        if success:
            self.streamers_cache.pop(twitch_username.lower(), None)

            await interaction.response.send_message(
                f"Стример **{twitch_username}** удален из отслеживаемых.", ephemeral=True
            )
            if interaction.guild is not None:
                logger.info(
                    f"Удален стример {twitch_username} для сервера {interaction.guild.name}"
                )
        else:
            await safe_send_error(
                interaction, f"Стример **{twitch_username}** не найден в списке отслеживаемых."
            )

    @app_commands.command(
        name="twitch_list", description="Показывает список отслеживаемых Twitch-стримеров"
    )
    async def twitch_list(self, interaction: discord.Interaction) -> None:
        """Показывает список отслеживаемых Twitch-стримеров.

        Args:
            interaction: Объект взаимодействия Discord
        """
        # Получаем список отслеживаемых стримеров для этого сервера
        if interaction.guild_id is None:
            await safe_send_error(interaction, "Ошибка: не удалось определить ID сервера.")
            return
        streamers = await self.data_manager.get_streamers(interaction.guild_id)

        if not streamers:
            await interaction.response.send_message(
                "На этом сервере нет отслеживаемых Twitch-стримеров.", ephemeral=True
            )
            return

        # Создаем эмбед со списком стримеров
        settings = get_settings()
        embed = discord.Embed(
            title="Отслеживаемые Twitch-стримеры",
            color=int(settings.twitch.embed_color.replace("#", ""), 16),
            timestamp=datetime.datetime.now(UTC),
        )

        # Группируем стримеров по каналу для уведомлений
        streamers_by_channel: dict[int, list[dict]] = {}
        for streamer in streamers:
            channel_id = streamer["channel_id"]
            if channel_id not in streamers_by_channel:
                streamers_by_channel[channel_id] = []
            streamers_by_channel[channel_id].append(streamer)

        # Добавляем информацию о стримерах в эмбед
        for channel_id, channel_streamers in streamers_by_channel.items():
            channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
            channel_name = (
                channel.mention
                if isinstance(channel, discord.TextChannel)
                else f"Канал {channel_id} (не найден)"
            )

            streamers_list = []
            for streamer in channel_streamers:
                username = streamer["twitch_username"]
                status = "🔴 В сети" if streamer["is_live"] else "⚫ Не в сети"
                streamers_list.append(f"[{username}](https://twitch.tv/{username}) - {status}")

            # Разбиваем список стримеров на чанки по 900 символов (с запасом)
            chunk: list[str] = []
            chunk_len = 0
            for entry in streamers_list:
                settings = get_settings()
                if chunk_len + len(entry) + 1 > settings.limits.twitch_streamers_chunk:
                    embed.add_field(
                        name=f"Канал: {channel_name}", value="\n".join(chunk), inline=False
                    )
                    chunk = []
                    chunk_len = 0
                chunk.append(entry)
                chunk_len += len(entry) + 1
            if chunk:
                embed.add_field(name=f"Канал: {channel_name}", value="\n".join(chunk), inline=False)
            if not streamers_list:
                embed.add_field(name=f"Канал: {channel_name}", value="Нет стримеров", inline=False)

        # Добавляем футер
        embed.set_footer(text=f"Всего отслеживается {len(streamers)} стримеров")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Делегирует ошибки app_commands единому обработчику (унифицированный embed)."""
        await handle_app_command_error(interaction, error)


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког TwitchCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(TwitchCog(bot))
    logger.info("Ког TwitchCog успешно загружен.")
