import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
import time
from typing import Optional, List, Dict, Tuple
import datetime

# Импортируем утилиты
from utils.error_handler import command_error_handler, safe_send
from utils.twitch_data_manager import TwitchDataManager
from utils.twitch_api import TwitchAPI

# Настраиваем логгер для модуля Twitch
logger = logging.getLogger("bot.twitch")

class TwitchCog(commands.Cog):
    """Ког для отслеживания стримов на Twitch."""

    def __init__(self, bot):
        self.bot = bot
        self.data_manager = TwitchDataManager()
        
        # Получаем Twitch API ключи из конфигурации
        self.client_id = self.bot.config.get("TWITCH_CLIENT_ID", "")
        self.client_secret = self.bot.config.get("TWITCH_CLIENT_SECRET", "")
        
        # Проверяем наличие ключей и что они не пустые
        if not self.client_id.strip() or not self.client_secret.strip():
            logger.warning("Не указаны TWITCH_CLIENT_ID и/или TWITCH_CLIENT_SECRET в конфигурации. "
                          "Функциональность отслеживания Twitch-стримов будет ограничена.")
            self.twitch_api = None
        else:
            self.twitch_api = TwitchAPI(self.client_id, self.client_secret)
        
        # Кеш для хранения информации о стримерах
        self.streamers_cache = {}  # {twitch_username: {'user_id': str, 'is_live': bool, 'stream_data': dict}}
        
        # Интервал проверки стримов (в секундах)
        self.check_interval = 60  # 1 минута
        
        # Флаг для отслеживания первого запуска
        self.first_run = True

    async def cog_load(self):
        """Вызывается при загрузке кога."""
        logger.info("Ког TwitchCog загружен")
        
        # Инициализируем таблицу в БД
        await self.data_manager.initialize_table()
        
        # Инициализируем Twitch API
        if self.twitch_api:
            await self.twitch_api.initialize()
            # Запускаем фоновую задачу для проверки стримов
            self.check_streams.start()
        else:
            logger.warning("Twitch API не инициализирован. Фоновая задача проверки стримов не запущена.")

    async def cog_unload(self):
        """Вызывается при выгрузке кога."""
        logger.info("Выгрузка кога TwitchCog")
        
        # Останавливаем фоновую задачу
        if self.check_streams.is_running():
            self.check_streams.cancel()
        
        # Закрываем Twitch API
        if self.twitch_api:
            await self.twitch_api.close()

    @tasks.loop(seconds=60)
    async def check_streams(self):
        """Фоновая задача для проверки статуса стримов."""
        try:
            # При первом запуске делаем паузу, чтобы бот успел полностью загрузиться
            if self.first_run:
                self.first_run = False
                logger.info("Первый запуск проверки стримов, ожидаем 30 секунд...")
                await asyncio.sleep(30)
            
            logger.debug("Начало проверки статуса стримов")
            
            # Получаем всех отслеживаемых стримеров
            streamers = await self.data_manager.get_all_streamers()
            if not streamers:
                logger.debug("Нет отслеживаемых стримеров")
                return
            
            # Группируем стримеров по имени пользователя для оптимизации запросов к API
            streamers_by_username = {}
            for streamer in streamers:
                username = streamer['twitch_username']
                if username not in streamers_by_username:
                    streamers_by_username[username] = []
                streamers_by_username[username].append(streamer)
            
            # Получаем информацию о пользователях Twitch
            usernames = list(streamers_by_username.keys())
            users = await self.twitch_api.get_users(usernames)
            
            # Создаем словарь {username: user_id}
            user_ids_by_username = {}
            for user in users:
                username = user['login'].lower()
                user_ids_by_username[username] = user['id']
                
                # Обновляем Twitch ID в базе данных, если он отсутствует
                for streamer in streamers_by_username.get(username, []):
                    if not streamer['twitch_id']:
                        await self.data_manager.update_twitch_id(username, user['id'])
            
            # Получаем информацию о текущих стримах
            user_ids = [user['id'] for user in users]
            streams = await self.twitch_api.get_streams(user_ids)
            
            # Создаем словарь {user_id: stream_data}
            streams_by_user_id = {stream['user_id']: stream for stream in streams}
            
            # Обновляем статус стримеров и отправляем уведомления
            for username, user_streamers in streamers_by_username.items():
                # Пропускаем стримеров, которых нет в ответе API
                if username not in user_ids_by_username:
                    logger.warning(f"Стример {username} не найден в Twitch API")
                    continue
                
                user_id = user_ids_by_username[username]
                is_live = user_id in streams_by_user_id
                stream_data = streams_by_user_id.get(user_id)
                
                # Обновляем кеш
                if username not in self.streamers_cache:
                    self.streamers_cache[username] = {'user_id': user_id, 'is_live': False, 'stream_data': None}
                
                # Проверяем, изменился ли статус стрима
                status_changed = self.streamers_cache[username]['is_live'] != is_live
                
                # Если стример только что начал стрим
                if is_live and status_changed:
                    logger.info(f"ОБНАРУЖЕН НОВЫЙ СТРИМ: Стример {username} начал стрим: {stream_data['title']}")
                    
                    # Обновляем статус в БД
                    await self.data_manager.update_streamer_status(username, True, stream_data['id'])
                    
                    # Берем первую запись стримера (так как бот работает только на одном сервере)
                    if user_streamers:
                        streamer_info = user_streamers[0]
                        guild_id = streamer_info['guild_id']
                        channel_id = streamer_info['channel_id']
                        
                        # Всегда отправляем уведомление при обнаружении нового стрима
                        logger.info(f"Отправка уведомления о стриме {username} в канал {channel_id}")
                        await self.send_stream_notification(
                            guild_id, channel_id, username, stream_data
                        )
                        
                        # Обновляем время последнего уведомления и ID стрима
                        await self.data_manager.update_notification_time(username, guild_id, stream_data['id'])
                
                # Если стример закончил стрим
                elif not is_live and status_changed:
                    logger.info(f"Стример {username} закончил стрим")
                    await self.data_manager.update_streamer_status(username, False)
                
                # Обновляем кеш
                self.streamers_cache[username]['is_live'] = is_live
                self.streamers_cache[username]['stream_data'] = stream_data
            
            logger.debug("Проверка статуса стримов завершена")
        
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса стримов: {e}", exc_info=True)

    @check_streams.before_loop
    async def before_check_streams(self):
        """Выполняется перед запуском фоновой задачи."""
        await self.bot.wait_until_ready()
        logger.info("Бот готов, запускаем проверку стримов")

    async def send_stream_notification(self, guild_id: int, channel_id: int, username: str, stream_data: Dict):
        """
        Отправляет уведомление о начале стрима в указанный канал.
        
        Args:
            guild_id: ID сервера Discord
            channel_id: ID канала для отправки уведомления
            username: Имя пользователя Twitch
            stream_data: Данные о стриме
        """
        try:
            logger.info(f"НАЧАЛО: Отправка уведомления о стриме {username} в канал {channel_id}")
            
            # Проверяем, что бот готов
            if not self.bot.is_ready():
                logger.error(f"Бот не готов при попытке отправить уведомление о стриме {username}")
                return
            
            # Получаем объект сервера (первый сервер, так как бот работает только на одном сервере)
            if not self.bot.guilds:
                logger.error("Бот не подключен ни к одному серверу")
                return
                
            guild = self.bot.guilds[0]
            logger.info(f"Используем сервер: {guild.name} (ID: {guild.id})")
            
            # Получаем объект канала
            channel = guild.get_channel(channel_id)
            if not channel:
                logger.error(f"Не найден канал с ID {channel_id} на сервере {guild.name}")
                
                # Пробуем найти канал по умолчанию
                default_channel_id = 1113813039083442296
                default_channel = guild.get_channel(default_channel_id)
                if default_channel:
                    logger.info(f"Используем канал по умолчанию {default_channel.name} ({default_channel_id})")
                    channel = default_channel
                else:
                    logger.error(f"Канал по умолчанию {default_channel_id} не найден")
                    return
            
            # Создаем эмбед с информацией о стриме
            embed = discord.Embed(
                title=stream_data['title'],
                url=f"https://twitch.tv/{username}",
                color=0x6441A4,  # Фирменный цвет Twitch
                timestamp=datetime.datetime.now()
            )
            
            # Добавляем информацию о стримере
            embed.set_author(
                name=f"{stream_data['user_name']} начал(а) стрим!",
                url=f"https://twitch.tv/{username}",
                icon_url="https://static.twitchcdn.net/assets/favicon-32-d6025c14e900565d6177.png"
            )
            
            # Добавляем превью стрима
            thumbnail_url = stream_data['thumbnail_url'].replace('{width}', '320').replace('{height}', '180')
            embed.set_image(url=thumbnail_url)
            
            # Добавляем информацию о категории
            embed.add_field(name="Категория", value=stream_data['game_name'] or "Не указана", inline=True)
            
            # Добавляем информацию о зрителях
            embed.add_field(name="Зрители", value=str(stream_data['viewer_count']), inline=True)
            
            # Добавляем футер
            embed.set_footer(text="Twitch Stream Notification")
            
            # Проверяем права бота в канале
            permissions = channel.permissions_for(guild.me)
            if not permissions.send_messages:
                logger.error(f"У бота нет прав на отправку сообщений в канал {channel.name} ({channel.id}) на сервере {guild.name}")
                return
                
            if not permissions.embed_links:
                logger.warning(f"У бота нет прав на отправку эмбедов в канал {channel.name} ({channel.id}) на сервере {guild.name}")
                # Продолжаем, но без эмбеда
            
            # Отправляем уведомление
            try:
                # Проверяем, можно ли упоминать @everyone
                mention_text = ""
                
                if permissions.embed_links:
                    logger.info(f"Отправка сообщения с эмбедом в канал {channel.name}")
                    message = await channel.send(
                        content=f"{mention_text}**{stream_data['user_name']}** начал(а) стрим на Twitch!",
                        embed=embed
                    )
                    logger.info(f"Сообщение успешно отправлено: {message.id}")
                else:
                    logger.info(f"Отправка текстового сообщения в канал {channel.name}")
                    message = await channel.send(
                        content=f"{mention_text}**{stream_data['user_name']}** начал(а) стрим на Twitch!\n"
                                f"Название: {stream_data['title']}\n"
                                f"Ссылка: https://twitch.tv/{username}"
                    )
                    logger.info(f"Сообщение успешно отправлено: {message.id}")
                
                logger.info(f"УСПЕХ: Отправлено уведомление о стриме {username} на сервер {guild.name} в канал {channel.name}")
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения в канал {channel.name}: {e}", exc_info=True)
                return
        
        except discord.Forbidden:
            logger.error(f"Недостаточно прав для отправки уведомления в канал {channel_id} на сервере {guild_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о стриме {username}: {e}", exc_info=True)

    @app_commands.command(
        name="twitch_add",
        description="Добавляет Twitch-стримера для отслеживания"
    )
    @app_commands.describe(
        twitch_username="Имя пользователя Twitch (без учета регистра)",
        channel="Канал для отправки уведомлений (по умолчанию - текущий канал)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def twitch_add(self, interaction: discord.Interaction, twitch_username: str, channel: Optional[discord.TextChannel] = None):
        """
        Добавляет Twitch-стримера для отслеживания.
        
        Args:
            interaction: Объект взаимодействия Discord
            twitch_username: Имя пользователя Twitch
            channel: Канал для отправки уведомлений (по умолчанию - текущий канал)
        """
        # Проверяем, инициализирован ли Twitch API
        if not self.twitch_api:
            await interaction.response.send_message(
                "Не указаны TWITCH_CLIENT_ID и/или TWITCH_CLIENT_SECRET в конфигурации бота. "
                "Обратитесь к администратору бота.",
                ephemeral=True
            )
            return
        
        # Определяем канал для уведомлений
        default_channel_id = 1113813039083442296
        if channel:
            notification_channel = channel
        else:
            # Пытаемся найти канал по умолчанию
            default_channel = interaction.guild.get_channel(default_channel_id)
            if default_channel:
                notification_channel = default_channel
                logger.info(f"Используется канал по умолчанию {default_channel.name} ({default_channel_id})")
            else:
                notification_channel = interaction.channel
                logger.warning(f"Канал по умолчанию {default_channel_id} не найден, используется текущий канал")
        
        # Проверяем, существует ли пользователь Twitch
        user = await self.twitch_api.get_user_by_username(twitch_username)
        if not user:
            await interaction.response.send_message(
                f"Пользователь Twitch с именем **{twitch_username}** не найден.",
                ephemeral=True
            )
            return
        
        # Добавляем стримера в базу данных
        success = await self.data_manager.add_streamer(
            interaction.guild_id, notification_channel.id, user['login'], user['id']
        )
        
        if success:
            # Добавляем стримера в кеш
            self.streamers_cache[user['login'].lower()] = {
                'user_id': user['id'],
                'is_live': False,
                'stream_data': None
            }
            
            # Проверяем, ведет ли стример стрим в данный момент
            is_live, stream_data = await self.twitch_api.is_user_live(user['id'])
            if is_live:
                # Обновляем статус в БД
                await self.data_manager.update_streamer_status(user['login'].lower(), True, stream_data['id'])
                
                # Обновляем кеш
                self.streamers_cache[user['login'].lower()]['is_live'] = True
                self.streamers_cache[user['login'].lower()]['stream_data'] = stream_data
                
                # Отправляем уведомление о стриме
                logger.info(f"Стример {user['login']} уже в сети, отправляем уведомление")
                await self.send_stream_notification(
                    interaction.guild_id, notification_channel.id, user['login'], stream_data
                )
                
                # Обновляем время последнего уведомления и ID стрима
                await self.data_manager.update_notification_time(user['login'].lower(), interaction.guild_id, stream_data['id'])
                
                await interaction.response.send_message(
                    f"Стример **{user['display_name']}** добавлен для отслеживания в канале {notification_channel.mention}.\n"
                    f"Стример сейчас в сети! Стрим: **{stream_data['title']}**\n"
                    f"Уведомление отправлено в канал.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Стример **{user['display_name']}** добавлен для отслеживания в канале {notification_channel.mention}.",
                    ephemeral=True
                )
            
            logger.info(f"Добавлен стример {user['login']} для сервера {interaction.guild.name}")
        else:
            await interaction.response.send_message(
                f"Не удалось добавить стримера **{twitch_username}**. Возможно, он уже отслеживается.",
                ephemeral=True
            )

    @app_commands.command(
        name="twitch_remove",
        description="Удаляет Twitch-стримера из отслеживаемых"
    )
    @app_commands.describe(
        twitch_username="Имя пользователя Twitch (без учета регистра)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def twitch_remove(self, interaction: discord.Interaction, twitch_username: str):
        """
        Удаляет Twitch-стримера из отслеживаемых.
        
        Args:
            interaction: Объект взаимодействия Discord
            twitch_username: Имя пользователя Twitch
        """
        # Удаляем стримера из базы данных
        success = await self.data_manager.remove_streamer(interaction.guild_id, twitch_username)
        
        if success:
            # Удаляем стримера из кеша, если он больше не отслеживается ни на одном сервере
            streamers = await self.data_manager.get_all_streamers()
            if not any(s['twitch_username'].lower() == twitch_username.lower() for s in streamers):
                self.streamers_cache.pop(twitch_username.lower(), None)
            
            await interaction.response.send_message(
                f"Стример **{twitch_username}** удален из отслеживаемых.",
                ephemeral=True
            )
            logger.info(f"Удален стример {twitch_username} для сервера {interaction.guild.name}")
        else:
            await interaction.response.send_message(
                f"Стример **{twitch_username}** не найден в списке отслеживаемых.",
                ephemeral=True
            )

    @app_commands.command(
        name="twitch_list",
        description="Показывает список отслеживаемых Twitch-стримеров"
    )
    async def twitch_list(self, interaction: discord.Interaction):
        """
        Показывает список отслеживаемых Twitch-стримеров.
        
        Args:
            interaction: Объект взаимодействия Discord
        """
        # Получаем список отслеживаемых стримеров для этого сервера
        streamers = await self.data_manager.get_streamers(interaction.guild_id)
        
        if not streamers:
            await interaction.response.send_message(
                "На этом сервере нет отслеживаемых Twitch-стримеров.",
                ephemeral=True
            )
            return
        
        # Создаем эмбед со списком стримеров
        embed = discord.Embed(
            title="Отслеживаемые Twitch-стримеры",
            color=0x6441A4,  # Фирменный цвет Twitch
            timestamp=datetime.datetime.now()
        )
        
        # Группируем стримеров по каналу для уведомлений
        streamers_by_channel = {}
        for streamer in streamers:
            channel_id = streamer['channel_id']
            if channel_id not in streamers_by_channel:
                streamers_by_channel[channel_id] = []
            streamers_by_channel[channel_id].append(streamer)
        
        # Добавляем информацию о стримерах в эмбед
        for channel_id, channel_streamers in streamers_by_channel.items():
            channel = interaction.guild.get_channel(channel_id)
            channel_name = channel.mention if channel else f"Канал {channel_id} (не найден)"
            
            streamers_list = []
            for streamer in channel_streamers:
                username = streamer['twitch_username']
                status = "🔴 В сети" if streamer['is_live'] else "⚫ Не в сети"
                streamers_list.append(f"[{username}](https://twitch.tv/{username}) - {status}")
            
            embed.add_field(
                name=f"Канал: {channel_name}",
                value="\n".join(streamers_list) or "Нет стримеров",
                inline=False
            )
        
        # Добавляем футер
        embed.set_footer(text=f"Всего отслеживается {len(streamers)} стримеров")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(TwitchCog(bot))
