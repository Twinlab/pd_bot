import discord
import asyncio
import logging
import os
import math
import yt_dlp
import glob
from collections import deque
from typing import Dict, List, Optional, Any, Union, Callable

# --- Настройка логирования ---
logger = logging.getLogger("music_module")
# Установим уровень INFO, чтобы видеть основные шаги
# В реальном приложении можно настроить более детально
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


# --- Константы и Конфигурация ---
DOWNLOADS_DIR = 'downloads'
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Цвета для Embeds
COLORS = {
    'DEFAULT': discord.Color.blue(),
    'ERROR':   discord.Color.red(),
    'SUCCESS': discord.Color.green(),
    'INFO':    discord.Color.gold()
}

# Загрузка основного конфига для PROXY_URL (если нужно)
try:
    from config import load_config as load_main_config
    _config = load_main_config()
    PROXY_URL = _config.get("PROXY_URL", None)
    logger.info(f"Proxy URL loaded from config: {PROXY_URL}")
except ImportError:
    logger.warning("Could not import main config. PROXY_URL will not be used.")
    PROXY_URL = None
except Exception as e:
    logger.error(f"Error loading main config: {e}", exc_info=True)
    PROXY_URL = None


# Опции для yt-dlp
YDL_OPTS_BASE = {
    'format': 'bestaudio/best',
    'outtmpl': f'{DOWNLOADS_DIR}/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True, # Скачиваем только один трек по ссылке, не плейлист
    'nocheckcertificate': True,
    'ignoreerrors': False, # Не игнорируем ошибки при скачивании
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch', # Поиск по умолчанию на YouTube
    'source_address': '0.0.0.0', # Fix для некоторых систем
    'proxy': PROXY_URL,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus', # Opus обычно лучше для ботов
        'preferredquality': '128', # Качество 128 kbps
    }],
    'logtostderr': False, # Не выводить логи yt-dlp в stderr
}

# Опции FFmpeg
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -loglevel warning', # Не выводить подробные логи ffmpeg
}

# --- Вспомогательные функции ---

def create_embed(title: str, description: str = "", color: discord.Color = COLORS['DEFAULT'], **kwargs: Any) -> discord.Embed:
    """Создает и возвращает объект discord.Embed."""
    embed = discord.Embed(title=title, description=description, color=color)
    for name, value in kwargs.items():
        if not value: continue
        if name == 'thumbnail': embed.set_thumbnail(url=value)
        elif name == 'footer': embed.set_footer(text=value)
        elif name == 'fields':
            for field_data in value:
                # Ожидаем кортеж (name, value, inline)
                inline = field_data[2] if len(field_data) > 2 else True
                embed.add_field(name=field_data[0], value=field_data[1], inline=inline)
        else: # Добавляем как обычное поле
             embed.add_field(name=name, value=value, inline=True)
    return embed

def format_duration(duration: Optional[Union[int, float, str]]) -> str:
    """Форматирует секунды в MM:SS или HH:MM:SS."""
    if duration is None: return "∞" # Для стримов
    try:
        duration = int(float(duration))
        if duration <= 0: return "00:00"
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        logger.warning(f"Could not format duration: {duration}")
        return "?:??"

# --- Класс Трека ---
class Track:
    """Представляет трек в очереди."""
    def __init__(self, info: Dict[str, Any], requester: discord.Member):
        self.url: str = info.get('webpage_url', info.get('original_url', ''))
        self.title: str = info.get('title', 'Unknown Title')
        self.duration: Optional[int] = info.get('duration')
        self.thumbnail: Optional[str] = info.get('thumbnail')
        self.uploader: Optional[str] = info.get('uploader')
        self.uploader_url: Optional[str] = info.get('uploader_url')
        self.requester: discord.Member = requester
        self.id: str = info.get('id', '')
        self.extractor: str = info.get('extractor_key', 'youtube').lower()

        # Путь к файлу будет установлен после скачивания
        self.filepath: Optional[str] = None

    def __str__(self) -> str:
        return f"**{self.title}** ({format_duration(self.duration)})"

    def to_embed_field(self, index: Optional[int] = None) -> tuple[str, str, bool]:
        """Возвращает кортеж для discord.Embed.add_field."""
        name = f"`{index}.` {self.title}" if index is not None else self.title
        value = f"`{format_duration(self.duration)}` | Запросил: {self.requester.mention}"
        if self.uploader:
            value += f"\nАвтор: [{self.uploader}]({self.uploader_url})" if self.uploader_url else f"\nАвтор: {self.uploader}"
        return (name, value, False)

# --- UI Компоненты ---

class PlayerControlView(discord.ui.View):
    """View с кнопками управления плеером."""
    def __init__(self, player: 'MusicPlayer', timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.player = player
        self._update_buttons()

    def _update_buttons(self):
        """Обновляет состояние кнопок (Pause/Resume, доступность)."""
        vc = self.player.voice_client
        can_control = vc is not None and self.player.current_track is not None

        # Кнопка Pause/Resume
        pause_resume_button = discord.utils.get(self.children, custom_id="music:pause_resume")
        if pause_resume_button:
            pause_resume_button.disabled = not can_control
            if self.player.is_paused:
                pause_resume_button.label = "▶️ Resume"
                pause_resume_button.style = discord.ButtonStyle.green
            else:
                pause_resume_button.label = "⏸️ Pause"
                pause_resume_button.style = discord.ButtonStyle.secondary

        # Кнопка Skip
        skip_button = discord.utils.get(self.children, custom_id="music:skip")
        if skip_button:
            skip_button.disabled = not can_control

        # Кнопка Stop
        stop_button = discord.utils.get(self.children, custom_id="music:stop")
        if stop_button:
            # Stop доступен всегда, когда бот в канале
            stop_button.disabled = vc is None

        # Кнопка Queue
        queue_button = discord.utils.get(self.children, custom_id="music:queue")
        if queue_button:
             # Queue доступна всегда
             queue_button.disabled = False

    async def _check_voice_channel(self, interaction: discord.Interaction) -> bool:
        """Проверяет, находится ли пользователь в том же канале, что и бот."""
        if not isinstance(interaction.user, discord.Member): return False # Не должно происходить
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Вы должны быть в голосовом канале!", ephemeral=True)
            return False
        if self.player.voice_client and interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⏸️ Pause", style=discord.ButtonStyle.secondary, custom_id="music:pause_resume", row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction): return

        if self.player.is_paused:
            await self.player.resume(interaction)
        else:
            await self.player.pause(interaction)
        # Обновляем кнопки после действия
        self._update_buttons()
        # Отвечаем на interaction (или редактируем, если pause/resume ответили)
        if not interaction.response.is_done():
            await interaction.response.edit_message(view=self)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.primary, custom_id="music:skip", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction): return
        await self.player.skip(interaction)
        # View обновится при старте нового трека или остановке

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="music:stop", row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction): return
        await self.player.stop(interaction)
        # View остановится и удалится сама в методе stop

    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.blurple, custom_id="music:queue", row=0)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
         # Для просмотра очереди не обязательно быть в голосовом канале
         await self.player.show_queue(interaction)
         # Отвечаем на interaction, если show_queue не ответил
         if not interaction.response.is_done():
              await interaction.response.defer() # Просто подтверждаем получение

    async def on_timeout(self):
        logger.info("PlayerControlView timed out.")
        # Можно убрать кнопки или изменить сообщение, но пока просто лог
        if self.player.now_playing_message:
            try:
                await self.player.now_playing_message.edit(view=None)
            except discord.NotFound: pass # Сообщение уже удалено
            except Exception as e: logger.warning(f"Failed to remove view on timeout: {e}")
        self.stop() # Останавливаем View

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Дополнительная проверка перед вызовом callback кнопки
        # Например, можно добавить проверку прав DJ
        return True


class SearchResultSelect(discord.ui.Select):
    """Выпадающий список для выбора трека из результатов поиска."""
    def __init__(self, player: 'MusicPlayer', interaction: discord.Interaction, entries: List[Dict]):
        self.player = player
        self.original_interaction = interaction # Interaction от команды /play
        self.entries = entries
        options = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict): continue # Пропускаем не-словари
            label = entry.get('title', f'Unknown Title {i+1}')
            if len(label) > 100: label = label[:97] + "..." # Обрезаем длинные названия
            desc = f"Автор: {entry.get('uploader', 'N/A')} | {format_duration(entry.get('duration'))}"
            if len(desc) > 100: desc = desc[:97] + "..."
            options.append(discord.SelectOption(label=label, description=desc, value=str(i)))

        if not options:
             options.append(discord.SelectOption(label="Ничего не найдено", value="-1", description="Попробуйте другой запрос"))

        super().__init__(placeholder="Выберите трек для добавления...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        """Обработка выбора трека."""
        selected_index = int(self.values[0])

        # Удаляем сообщение с выбором
        try:
            await interaction.message.delete()
        except discord.NotFound: pass
        except Exception as e: logger.warning(f"Failed to delete search result message: {e}")

        if selected_index == -1:
            await interaction.response.send_message("Поиск отменен.", ephemeral=True, delete_after=10)
            return

        if not (0 <= selected_index < len(self.entries)):
             await interaction.response.send_message("Неверный выбор.", ephemeral=True, delete_after=10)
             return

        selected_entry = self.entries[selected_index]
        url = selected_entry.get('webpage_url', selected_entry.get('original_url', selected_entry.get('url')))

        if not url:
            await interaction.response.send_message("❌ Ошибка: Не удалось получить URL для выбранного трека.", ephemeral=True)
            return

        # Проверяем голосовой канал пользователя, который сделал выбор
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
             await interaction.response.send_message("Вы должны быть в голосовом канале, чтобы добавить трек!", ephemeral=True)
             return

        # Подключаемся к каналу пользователя, если еще не там
        connected = await self.player.connect(interaction.user.voice.channel)
        if not connected:
             await interaction.response.send_message("Не удалось подключиться к вашему голосовому каналу.", ephemeral=True)
             return

        # Отправляем сообщение о добавлении и начинаем скачивание/добавление
        # Используем original_interaction для получения автора команды /play
        requester = self.original_interaction.user
        await interaction.response.send_message(f"⏳ Добавляем '{selected_entry.get('title', 'выбранный трек')}'...", ephemeral=True)
        await self.player.queue_track(url, requester, interaction) # Передаем interaction для ответа о результате


class SearchView(discord.ui.View):
    """View, содержащая выпадающий список результатов поиска."""
    def __init__(self, player: 'MusicPlayer', interaction: discord.Interaction, entries: List[Dict], timeout=60.0):
        super().__init__(timeout=timeout)
        self.player = player
        self.original_interaction = interaction
        self.add_item(SearchResultSelect(player, interaction, entries))

    async def on_timeout(self):
        logger.info("SearchView timed out.")
        try:
            # Пытаемся отредактировать исходное сообщение от /play (если оно еще есть)
            await self.original_interaction.edit_original_response(content="⏱️ Время выбора трека истекло.", view=None, embed=None)
        except discord.NotFound: pass
        except Exception as e: logger.warning(f"Failed to edit original search message on timeout: {e}")
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Разрешаем выбирать только тому, кто вызвал команду /play
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("Только пользователь, запустивший поиск, может выбрать трек.", ephemeral=True)
            return False
        return True


# --- Класс Музыкального Плеера ---

class MusicPlayer:
    """Управляет состоянием и воспроизведением музыки (для одного сервера)."""

    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.TextChannel] = None # Канал для сообщений плеера
        self.queue: deque[Track] = deque()
        self.current_track: Optional[Track] = None
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.loop = asyncio.get_event_loop()
        self.now_playing_message: Optional[discord.Message] = None
        self.player_view: Optional[PlayerControlView] = None
        self._volume: float = 0.5 # Внутренняя громкость
        self._play_next_task: Optional[asyncio.Task] = None
        self._current_ffmpeg_process = None # Для возможного управления процессом ffmpeg

    # --- Управление подключением ---

    async def connect(self, channel: discord.VoiceChannel) -> bool:
        """Подключается к указанному голосовому каналу или перемещается в него."""
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel == channel:
                return True # Уже в нужном канале
            try:
                logger.info(f"Moving to voice channel: {channel.name} ({channel.id})")
                await self.voice_client.move_to(channel)
                return True
            except asyncio.TimeoutError:
                logger.error(f"Timeout moving to voice channel: {channel.name}")
                return False
            except Exception as e:
                logger.error(f"Error moving to voice channel {channel.name}: {e}", exc_info=True)
                # Попробуем переподключиться полностью
                await self.disconnect() # Сначала отключаемся
                # pass # Продолжаем попытку подключения ниже
            # Если move_to не удалось, пробуем подключиться заново
        try:
            logger.info(f"Connecting to voice channel: {channel.name} ({channel.id})")
            self.voice_client = await channel.connect(timeout=30.0, reconnect=True)
            logger.info(f"Successfully connected to {channel.name}")
            return True
        except asyncio.TimeoutError:
            logger.error(f"Timeout connecting to voice channel: {channel.name}")
            self.voice_client = None
            return False
        except discord.ClientException as e:
             logger.error(f"ClientException connecting to {channel.name}: {e}")
             # Возможно, бот уже подключен где-то еще (хотя мы один сервер)
             # Попробуем найти существующее подключение
             if channel.guild.voice_client:
                 self.voice_client = channel.guild.voice_client
                 logger.warning(f"Found existing voice client in {self.voice_client.channel.name}. Moving if necessary.")
                 return await self.connect(channel) # Рекурсивный вызов для перемещения
             self.voice_client = None
             return False
        except Exception as e:
            logger.error(f"Error connecting to voice channel {channel.name}: {e}", exc_info=True)
            self.voice_client = None
            return False

    async def disconnect(self, interaction: Optional[discord.Interaction] = None):
        """Отключается от голосового канала и очищает ресурсы."""
        logger.info("Disconnecting and cleaning up player...")
        if self._play_next_task:
            self._play_next_task.cancel()
            self._play_next_task = None

        if self.voice_client and self.voice_client.is_connected():
            logger.info(f"Stopping playback and disconnecting from {self.voice_client.channel.name}")
            self.voice_client.stop() # Останавливаем текущее воспроизведение
            await self.voice_client.disconnect(force=True) # Принудительное отключение
            self.voice_client = None
        else:
             logger.info("Voice client not connected or already disconnected.")

        await self.cleanup(clear_queue=True) # Очищаем все

        if interaction and not interaction.response.is_done():
             # Если disconnect вызван из команды stop, отвечаем
             await interaction.response.send_message("⏹️ Воспроизведение остановлено, бот отключен.", ephemeral=True)
        elif self.text_channel:
             # Если автоотключение, отправляем сообщение
             try:
                 await self.text_channel.send(embed=create_embed("👋 Автоотключение", "Бот отключен из-за неактивности или пустого канала.", COLORS['INFO']))
             except Exception as e:
                 logger.warning(f"Failed to send auto-disconnect message: {e}")

        logger.info("Player disconnected and cleaned up.")

    # --- Управление очередью и треками ---

    async def queue_track(self, url: str, requester: discord.Member, interaction: Optional[discord.Interaction] = None):
        """Скачивает трек и добавляет его в очередь."""
        response_method = interaction.followup.send if interaction else (self.text_channel.send if self.text_channel else None)
        edit_method = interaction.edit_original_response if interaction else None # Для обновления сообщения о загрузке

        loading_msg = None
        if edit_method:
            try:
                # Если есть interaction, редактируем исходное сообщение "Добавляем..."
                await edit_method(content="🔄 Скачивание трека...")
            except discord.NotFound: # Сообщение могло быть удалено
                 edit_method = None # Не можем редактировать, будем отправлять новое
                 if response_method:
                     loading_msg = await response_method(embed=create_embed("🔄 Загрузка", "Скачиваем трек..."), wait=True if interaction else False)
            except Exception as e:
                 logger.warning(f"Failed to edit loading message: {e}")
                 edit_method = None
                 if response_method:
                     loading_msg = await response_method(embed=create_embed("🔄 Загрузка", "Скачиваем трек..."), wait=True if interaction else False)
        elif response_method:
             loading_msg = await response_method(embed=create_embed("🔄 Загрузка", "Скачиваем трек..."), wait=True if interaction else False)

        update_msg_method = loading_msg.edit if loading_msg and not edit_method else edit_method

        try:
            logger.info(f"Downloading track: {url}")
            track_info = await self._download_track(url)
            if not track_info:
                raise ValueError("Не удалось получить информацию о треке.")

            track = Track(track_info, requester)
            track.filepath = track_info.get('filepath') # Получаем путь к файлу из результата _download_track

            if not track.filepath or not os.path.exists(track.filepath):
                 raise FileNotFoundError(f"Скачанный файл не найден: {track.filepath}")
            if os.path.getsize(track.filepath) == 0:
                 raise ValueError(f"Скачанный файл имеет нулевой размер: {track.filepath}")

            self.queue.append(track)
            logger.info(f"Track added to queue: {track.title}")

            # Отправляем подтверждение
            embed = create_embed(
                "✅ Трек добавлен", f"[{track.title}]({track.url})", COLORS['SUCCESS'],
                thumbnail=track.thumbnail,
                fields=[
                    ("Длительность", format_duration(track.duration), True),
                    ("Запросил", requester.mention, True),
                    ("Позиция", str(len(self.queue)), True)
                ]
            )
            if update_msg_method:
                await update_msg_method(content=None, embed=embed, view=None) # Убираем view если был поиск
            elif response_method:
                 await response_method(embed=embed) # Отправляем новое сообщение

            # Если ничего не играет и бот подключен, запускаем воспроизведение
            if not self.is_playing and self.voice_client and self.voice_client.is_connected():
                # Не используем await здесь, play_next запустится в фоне
                self.start_playback_loop()

        except yt_dlp.utils.DownloadError as e:
            logger.error(f"yt-dlp download error for {url}: {e}", exc_info=True)
            error_embed = create_embed("❌ Ошибка загрузки", f"Не удалось скачать трек. Возможно, он недоступен или ссылка неверна.\n`{e}`", COLORS['ERROR'])
            if update_msg_method: await update_msg_method(content=None, embed=error_embed, view=None)
            elif response_method: await response_method(embed=error_embed)
        except FileNotFoundError as e:
             logger.error(f"File not found after download for {url}: {e}", exc_info=True)
             error_embed = create_embed("❌ Ошибка файла", f"Скачанный аудиофайл не найден.\n`{e}`", COLORS['ERROR'])
             if update_msg_method: await update_msg_method(content=None, embed=error_embed, view=None)
             elif response_method: await response_method(embed=error_embed)
        except ValueError as e: # Ошибка нулевого размера файла
             logger.error(f"File size error for {url}: {e}", exc_info=True)
             error_embed = create_embed("❌ Ошибка файла", f"Скачанный файл поврежден (нулевой размер).\n`{e}`", COLORS['ERROR'])
             if update_msg_method: await update_msg_method(content=None, embed=error_embed, view=None)
             elif response_method: await response_method(embed=error_embed)
        except Exception as e:
            logger.error(f"Error adding track {url}: {e}", exc_info=True)
            error_embed = create_embed("❌ Неизвестная ошибка", f"Произошла ошибка при добавлении трека:\n`{e}`", COLORS['ERROR'])
            if update_msg_method: await update_msg_method(content=None, embed=error_embed, view=None)
            elif response_method: await response_method(embed=error_embed)

    async def _download_track(self, url: str) -> Optional[Dict[str, Any]]:
        """Скачивает трек с помощью yt-dlp и возвращает информацию."""
        ydl_opts = YDL_OPTS_BASE.copy()
        try:
            # Запускаем yt-dlp в отдельном потоке, чтобы не блокировать event loop
            ytdl = yt_dlp.YoutubeDL(ydl_opts)
            info = await self.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=True))

            if not info:
                logger.warning(f"yt-dlp returned no info for {url}")
                return None

            # Если это результат поиска или плейлист, берем первый элемент
            if 'entries' in info:
                if not info['entries']:
                    logger.warning(f"yt-dlp returned empty 'entries' for {url}")
                    return None
                info = info['entries'][0]
                if not info: # Если первый элемент плейлиста None
                     logger.warning(f"yt-dlp returned None entry in 'entries' for {url}")
                     return None


            # Определяем путь к скачанному файлу
            # yt-dlp с postprocessor'ом может изменить расширение
            # Используем prepare_filename, чтобы получить ожидаемое имя *до* постпроцессинга
            base_filename_tmpl = ydl_opts['outtmpl']
            # Заменяем плейсхолдеры в шаблоне на реальные значения из info
            # Это не идеально, т.к. yt-dlp может делать доп. санитизацию
            try:
                 expected_base = ytdl.prepare_filename(info).rsplit('.', 1)[0]
            except Exception: # Если prepare_filename падает
                 # Пытаемся угадать по ID и названию
                 extractor = info.get('extractor_key', 'unknown').lower()
                 track_id = info.get('id', 'unknown_id')
                 title = info.get('title', 'unknown_title')
                 # Простая санитизация
                 safe_title = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in title)[:100]
                 expected_base = f"{DOWNLOADS_DIR}/{extractor}-{track_id}-{safe_title}"


            # Ищем файл с нужным расширением (opus) или любым другим аудио расширением
            preferred_ext = '.' + ydl_opts['postprocessors'][0]['preferredcodec'] # .opus
            filepath = expected_base + preferred_ext

            if not os.path.exists(filepath):
                logger.warning(f"File {filepath} not found. Searching with glob: {expected_base}.*")
                # Ищем любой файл, начинающийся с ожидаемого имени
                found_files = glob.glob(f"{expected_base}.*")
                if found_files:
                    # Пытаемся найти аудио файл
                    audio_files = [f for f in found_files if f.lower().endswith(('.opus', '.mp3', '.ogg', '.m4a', '.aac', '.wav', '.flac'))]
                    if audio_files:
                         filepath = audio_files[0] # Берем первый найденный аудио файл
                         logger.info(f"Found audio file via glob: {filepath}")
                    else:
                         filepath = found_files[0] # Берем любой файл, если аудио не найдено
                         logger.warning(f"Could not find specific audio extension, using first match: {filepath}")
                else:
                    logger.error(f"Could not find any downloaded file matching pattern: {expected_base}.*")
                    return None # Файл не найден

            info['filepath'] = filepath # Добавляем путь к файлу в словарь
            return info

        except yt_dlp.utils.DownloadError as e:
            # Эти ошибки обрабатываются в queue_track
            logger.warning(f"yt-dlp DownloadError during download: {e}")
            raise # Передаем ошибку выше
        except Exception as e:
            logger.error(f"Unexpected error during track download ({url}): {e}", exc_info=True)
            return None # Возвращаем None при других ошибках

    # --- Управление воспроизведением ---

    def start_playback_loop(self):
        """Запускает цикл воспроизведения, если он еще не запущен."""
        if self._play_next_task and not self._play_next_task.done():
            logger.debug("Playback loop already running.")
            return

        logger.info("Starting playback loop...")
        self._play_next_task = self.loop.create_task(self.play_next())

    async def play_next(self):
        """Основной цикл воспроизведения: берет трек из очереди и играет."""
        try:
            if not self.voice_client or not self.voice_client.is_connected():
                logger.warning("play_next called but voice client is not connected.")
                await self.cleanup()
                return

            if self.is_playing: # Предотвращаем одновременный запуск
                 logger.debug("play_next called while already playing. Ignoring.")
                 return

            if not self.queue:
                logger.info("Queue is empty. Playback finished.")
                await self.cleanup(clear_queue=False) # Очищаем только состояние, не очередь
                # Можно добавить таймер автоотключения здесь
                return

            self.current_track = self.queue.popleft()
            logger.info(f"Playing next track: {self.current_track.title}")

            if not self.current_track.filepath or not os.path.exists(self.current_track.filepath):
                 logger.error(f"Filepath missing or file not found for track: {self.current_track.title} ({self.current_track.filepath})")
                 await self.send_error_message(f"Ошибка: Файл для трека '{self.current_track.title}' не найден.")
                 self.current_track = None
                 self.start_playback_loop() # Пытаемся сыграть следующий
                 return

            try:
                source = discord.FFmpegPCMAudio(self.current_track.filepath, **FFMPEG_OPTIONS)
                # Запоминаем процесс ffmpeg, если нужно будет его убить
                # self._current_ffmpeg_process = source._process
                source_volumed = discord.PCMVolumeTransformer(source, volume=self._volume)
            except Exception as e:
                logger.error(f"Error creating FFmpegPCMAudio for {self.current_track.filepath}: {e}", exc_info=True)
                await self.send_error_message(f"Ошибка FFmpeg при обработке трека '{self.current_track.title}'.")
                # Удаляем битый файл?
                await self._cleanup_track_file(self.current_track)
                self.current_track = None
                self.start_playback_loop() # Пытаемся сыграть следующий
                return

            # Воспроизводим
            self.voice_client.play(source_volumed, after=lambda e: self.loop.create_task(self._after_playback(e)))
            self.is_playing = True
            self.is_paused = False
            logger.info(f"Playback started for: {self.current_track.title}")

            # Отправляем или обновляем сообщение "Сейчас играет"
            await self._update_now_playing_message()

        except Exception as e:
            logger.error(f"Error in play_next loop: {e}", exc_info=True)
            await self.send_error_message("Произошла критическая ошибка в цикле воспроизведения.")
            # Попытка восстановиться? Или просто остановиться?
            await self.stop() # Безопаснее остановиться

    async def _after_playback(self, error: Optional[Exception]):
        """Callback, вызываемый после завершения или ошибки воспроизведения трека."""
        logger.debug(f"_after_playback called. Error: {error}")
        finished_track = self.current_track
        self.is_playing = False
        self.current_track = None
        # self._current_ffmpeg_process = None

        if error:
            logger.error(f"Playback error: {error}", exc_info=error)
            await self.send_error_message(f"Ошибка во время воспроизведения трека '{finished_track.title if finished_track else ''}': `{error}`")

        # Очищаем файл завершенного трека
        if finished_track:
            await self._cleanup_track_file(finished_track)

        # Если в очереди есть еще треки и бот все еще подключен, запускаем следующий
        if self.queue and self.voice_client and self.voice_client.is_connected():
            self.start_playback_loop()
        elif self.voice_client and self.voice_client.is_connected():
             # Очередь пуста, но бот еще подключен
             logger.info("Queue finished, but client still connected.")
             await self.cleanup(clear_queue=False) # Очищаем состояние
             # Можно запустить таймер автоотключения здесь
        else:
             # Бот отключился во время воспроизведения?
             logger.info("Playback finished and client disconnected.")
             await self.cleanup(clear_queue=False) # Очищаем на всякий случай

    async def pause(self, interaction: Optional[discord.Interaction] = None):
        """Приостанавливает воспроизведение."""
        if self.voice_client and self.is_playing and not self.is_paused:
            logger.info("Pausing playback.")
            self.voice_client.pause()
            self.is_paused = True
            if interaction:
                await interaction.response.send_message("⏸️ Воспроизведение приостановлено.", ephemeral=True)
            await self._update_now_playing_message() # Обновляем View
        elif interaction:
             await interaction.response.send_message("Сейчас ничего не играет или уже на паузе.", ephemeral=True)

    async def resume(self, interaction: Optional[discord.Interaction] = None):
        """Возобновляет воспроизведение."""
        if self.voice_client and self.is_paused:
            logger.info("Resuming playback.")
            self.voice_client.resume()
            self.is_paused = False
            if interaction:
                await interaction.response.send_message("▶️ Воспроизведение возобновлено.", ephemeral=True)
            await self._update_now_playing_message() # Обновляем View
        elif interaction:
             await interaction.response.send_message("Воспроизведение не на паузе.", ephemeral=True)

    async def skip(self, interaction: Optional[discord.Interaction] = None):
        """Пропускает текущий трек."""
        if self.voice_client and self.is_playing:
            logger.info(f"Skipping track: {self.current_track.title if self.current_track else 'Unknown'}")
            skipped_title = self.current_track.title if self.current_track else "текущий трек"
            self.voice_client.stop() # Останавливаем, _after_playback запустит следующий
            if interaction:
                 # Отвечаем сразу, т.к. следующий трек начнется не мгновенно
                 await interaction.response.send_message(f"⏭️ Трек '{skipped_title}' пропущен.", ephemeral=True)
            # _after_playback обработает остальное
        elif interaction:
             await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)

    async def stop(self, interaction: Optional[discord.Interaction] = None):
        """Останавливает воспроизведение, очищает очередь и отключается."""
        logger.info("Stop command received.")
        # Полная очистка и отключение
        await self.disconnect(interaction)

    # --- Управление громкостью (пример) ---
    async def set_volume(self, volume: float, interaction: Optional[discord.Interaction] = None):
         """Устанавливает громкость (от 0.0 до 2.0)."""
         if not (0.0 <= volume <= 2.0):
             if interaction: await interaction.response.send_message("Громкость должна быть от 0 до 200.", ephemeral=True)
             return

         self._volume = volume
         if self.voice_client and self.voice_client.source:
             self.voice_client.source.volume = self._volume
             logger.info(f"Volume set to {volume * 100}%")
             if interaction: await interaction.response.send_message(f"🔊 Громкость установлена на {int(volume * 100)}%", ephemeral=True)
         elif interaction:
             await interaction.response.send_message(f"🔊 Громкость будет применена к следующему треку ({int(volume * 100)}%).", ephemeral=True)


    # --- Отображение информации ---

    async def show_queue(self, interaction: discord.Interaction):
        """Отправляет сообщение с текущей очередью."""
        if not self.current_track and not self.queue:
            await interaction.response.send_message(embed=create_embed("ℹ️ Очередь пуста", color=COLORS['INFO']), ephemeral=True)
            return

        embed = discord.Embed(title="🎵 Очередь воспроизведения", color=COLORS['DEFAULT'])
        description_lines = []

        if self.current_track:
            state = "⏸️" if self.is_paused else "▶️"
            description_lines.append(f"**{state} Сейчас играет:**")
            name, value, _ = self.current_track.to_embed_field()
            description_lines.append(f"{name}\n{value}")
            description_lines.append("") # Пустая строка

        if self.queue:
            description_lines.append("**⏱️ В очереди:**")
            queue_list = list(self.queue)
            total_duration = sum(t.duration for t in queue_list if t.duration) + (self.current_track.duration if self.current_track and self.current_track.duration else 0)

            for i, track in enumerate(queue_list[:15], 1): # Показываем до 15 треков
                name, value, _ = track.to_embed_field(index=i)
                description_lines.append(f"{name}\n{value}")

            if len(queue_list) > 15:
                description_lines.append(f"\n*...и еще {len(queue_list) - 15} трек(ов)*")

            embed.set_footer(text=f"Всего треков: {len(queue_list) + (1 if self.current_track else 0)} | Общая длительность: {format_duration(total_duration)}")
        elif self.current_track:
             embed.set_footer(text=f"Всего треков: 1 | Общая длительность: {format_duration(self.current_track.duration)}")


        embed.description = "\n".join(description_lines)[:4096] # Ограничение длины

        await interaction.response.send_message(embed=embed, ephemeral=True) # Отправляем эфемерно

    async def _update_now_playing_message(self):
        """Обновляет или отправляет сообщение 'Сейчас играет'."""
        if not self.text_channel:
            logger.warning("_update_now_playing_message called without text_channel.")
            return

        embed = self._create_now_playing_embed()
        view = self.player_view or PlayerControlView(self)
        view._update_buttons() # Обновляем состояние кнопок перед отправкой/редактированием

        if self.now_playing_message:
            try:
                await self.now_playing_message.edit(embed=embed, view=view)
                logger.debug("Updated 'Now Playing' message.")
            except discord.NotFound:
                logger.warning("'Now Playing' message not found, sending new one.")
                self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
            except Exception as e:
                logger.error(f"Failed to edit 'Now Playing' message: {e}", exc_info=True)
                # Попробуем отправить новое сообщение
                try:
                     self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
                except Exception as send_e:
                     logger.error(f"Failed to send new 'Now Playing' message: {send_e}", exc_info=True)
                     self.now_playing_message = None # Сбрасываем, чтобы не пытаться редактировать снова
        else:
            try:
                self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
                logger.info("Sent 'Now Playing' message.")
            except Exception as e:
                logger.error(f"Failed to send 'Now Playing' message: {e}", exc_info=True)
                self.now_playing_message = None

        self.player_view = view # Сохраняем View

    def _create_now_playing_embed(self) -> discord.Embed:
        """Создает Embed для сообщения 'Сейчас играет'."""
        if not self.current_track:
            return create_embed("⏹️ Ничего не играет", color=COLORS['INFO'])

        track = self.current_track
        state = "⏸️ Пауза:" if self.is_paused else "▶️ Сейчас играет:"
        embed = create_embed(state, f"[{track.title}]({track.url})", COLORS['DEFAULT'], thumbnail=track.thumbnail)

        fields = [
            ("Длительность", format_duration(track.duration), True),
            ("Запросил", track.requester.mention, True),
        ]
        if track.uploader:
             uploader_text = f"[{track.uploader}]({track.uploader_url})" if track.uploader_url else track.uploader
             fields.append(("Автор", uploader_text, True))

        if self.queue:
             next_track = self.queue[0]
             fields.append(("Следующий", f"[{next_track.title}]({next_track.url})", False))

        embed.add_field(name="\u200b", value="\u200b", inline=False) # Пустое поле для разделения
        for name, value, inline in fields:
             embed.add_field(name=name, value=value, inline=inline)

        return embed

    async def send_error_message(self, message: str):
        """Отправляет сообщение об ошибке в text_channel, если он установлен."""
        if self.text_channel:
            try:
                await self.text_channel.send(embed=create_embed("❌ Ошибка", message, COLORS['ERROR']))
            except Exception as e:
                logger.error(f"Failed to send error message to text channel: {e}")
        else:
            logger.warning(f"Cannot send error message, text_channel not set. Error: {message}")

    # --- Очистка ---

    async def cleanup(self, clear_queue: bool = True):
        """Очищает состояние плеера и временные файлы."""
        logger.debug(f"Cleanup called. clear_queue={clear_queue}")
        self.is_playing = False
        self.is_paused = False
        self.current_track = None
        # self._current_ffmpeg_process = None # Если управляли процессом

        # Останавливаем и удаляем View
        if self.player_view:
            self.player_view.stop()
            if self.now_playing_message:
                 try: await self.now_playing_message.edit(view=None)
                 except discord.NotFound: pass
                 except Exception as e: logger.warning(f"Failed to remove view during cleanup: {e}")
            self.player_view = None
        # Удаляем сообщение "Now Playing"
        if self.now_playing_message:
             try: await self.now_playing_message.delete()
             except discord.NotFound: pass
             except Exception as e: logger.warning(f"Failed to delete 'Now Playing' message during cleanup: {e}")
             self.now_playing_message = None

        files_to_delete = set()
        if clear_queue:
            logger.debug(f"Clearing queue (contains {len(self.queue)} items).")
            while self.queue:
                track = self.queue.popleft()
                if track.filepath:
                    files_to_delete.add(track.filepath)
            self.queue.clear() # Убедимся, что она точно пуста
        else:
             # Если не очищаем очередь, нужно проверить файлы только для current_track (которого уже нет)
             # Файлы треков в очереди НЕ удаляем
             logger.debug("Cleanup without clearing queue.")
             pass # Файлы в очереди остаются

        # Удаляем собранные файлы
        await self._cleanup_files(files_to_delete)

        # Сбрасываем канал (не сбрасываем при clear_queue=False, т.к. очередь может продолжиться)
        # if clear_queue:
        #      self.text_channel = None

        logger.debug("Cleanup finished.")


    async def _cleanup_track_file(self, track: Track):
        """Удаляет файл указанного трека, если он больше не нужен."""
        if not track or not track.filepath: return
        # Проверяем, есть ли этот же файл в очереди
        is_needed = any(t.filepath == track.filepath for t in self.queue)
        if not is_needed:
            await self._cleanup_files({track.filepath})
        else:
            logger.debug(f"File {track.filepath} is still needed by queue, not deleting.")

    async def _cleanup_files(self, filepaths: set[str]):
        """Безопасно удаляет файлы из переданного множества путей."""
        for path in filepaths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"Deleted file: {path}")
                except OSError as e:
                    logger.error(f"Error deleting file {path}: {e}")
            # else: logger.debug(f"File path invalid or file not found for deletion: {path}")


# --- Глобальные функции поиска (для использования в коге) ---

async def search_youtube(query: str, max_results: int = 10) -> Optional[List[Dict[str, Any]]]:
    """Ищет видео на YouTube без скачивания."""
    logger.info(f"Searching YouTube for '{query}' (max_results={max_results})")
    ydl_opts = {
        'format': 'bestaudio', # Нужно для получения длительности
        'extract_flat': 'discard_in_playlist', # Не извлекать инфо о каждом видео плейлиста
        'playlistend': max_results,
        'quiet': True,
        'no_warnings': True,
        'default_search': f'ytsearch{max_results}',
        'source_address': '0.0.0.0',
        'proxy': PROXY_URL,
        'logtostderr': False,
        'ignoreerrors': True, # Игнорировать ошибки отдельных видео
    }
    try:
        ytdl = yt_dlp.YoutubeDL(ydl_opts)
        # Запускаем в executor'е
        info = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ytdl.extract_info(query, download=False)
        )

        if not info or not info.get('entries'):
            logger.warning(f"YouTube search for '{query}' returned no entries.")
            return None

        # Фильтруем None значения, которые могут появиться из-за ignoreerrors
        valid_entries = [entry for entry in info['entries'] if isinstance(entry, dict) and entry.get('url')]
        logger.info(f"Found {len(valid_entries)} valid entries for '{query}'")
        return valid_entries

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError during search for '{query}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during YouTube search for '{query}': {e}", exc_info=True)
        return None
