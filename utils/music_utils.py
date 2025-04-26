import discord
import asyncio
from discord.ext import commands
import logging
import os
import math
import yt_dlp
import json
from collections import deque
import glob
from typing import Dict, List, Optional, Set, Any, Union, Callable
import subprocess # Для stderr FFmpeg
import discord.ui # Для интерактивных компонентов

logger = logging.getLogger("music")

DOWNLOADS_DIR = 'downloads'
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

COLORS = {
    'DEFAULT': discord.Color.blue(),
    'ERROR':   discord.Color.red(),
    'SUCCESS': discord.Color.green()
}

from config import load_config as load_main_config

_config = load_main_config()
# Опции для yt-dlp
YDL_OPTS = {
    'format': 'bestaudio/best',
    'outtmpl': f'{DOWNLOADS_DIR}/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'proxy': _config.get("PROXY_URL", None),
    # Возвращаем mp3 как предпочтительный кодек
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3', # Возвращено на 'mp3'
        'preferredquality': '192',
    }],
}

def create_embed(title: str, description: str, color: discord.Color = COLORS['DEFAULT'], **kwargs: Any) -> discord.Embed:
    """Создает и возвращает объект discord.Embed."""
    embed = discord.Embed(title=title, description=description, color=color)
    for name, value in kwargs.items():
        if not value: continue
        if name == 'thumbnail': embed.set_thumbnail(url=value)
        elif name == 'footer': embed.set_footer(text=value)
        elif name == 'fields':
            for field in value: embed.add_field(name=field[0], value=field[1], inline=field[2] if len(field) > 2 else True)
        else: embed.add_field(name=name, value=value, inline=True)
    return embed

def format_duration(duration: Optional[Union[int, float, str]]) -> str:
    """Форматирует секунды в MM:SS или HH:MM:SS."""
    if not duration: return "∞"
    try:
        duration = int(float(duration))
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError): return "?:??"

class MusicPlayer:
    """Управляет состоянием воспроизведения музыки для одного сервера."""
    # Возвращаем к версии до рефакторинга
    def __init__(self, bot):
        self.bot = bot
        self.queue = deque()
        self.current: Optional[Dict] = None
        self.volume = 0.5
        self.text_channel: Optional[discord.TextChannel] = None
        self.now_playing_message: Optional[discord.Message] = None
        self.skip_votes: Set[int] = set()
        self.loop = asyncio.get_event_loop()
        self.is_playing_next = False
        self.is_paused = False
        self.view: Optional[PlayerControlView] = None # Добавляем для хранения View

    async def send_embed(self, ctx, title, description, color=COLORS['DEFAULT'], **kwargs):
        # Используем send_message для централизации отправки
        await self.send_message(ctx, title, description, color, **kwargs)

    async def send_message(self, ctx: Optional[commands.Context], title: str, description: str, color: discord.Color = COLORS['DEFAULT'], **kwargs):
        """Отправляет эмбед-сообщение в канал команды или запомненный канал."""
        if ctx and not self.text_channel: self.text_channel = ctx.channel
        channel_to_send = self.text_channel or (ctx.channel if ctx else None)
        if channel_to_send:
            try: await channel_to_send.send(embed=create_embed(title, description, color, **kwargs))
            except Exception as e: logger.error(f"Не удалось отправить сообщение в {channel_to_send.id}: {e}")
        else: logger.error("Не удалось определить канал для отправки сообщения плеера.")


    async def add_track(self, ctx, url_or_search):
        """Скачивает трек (или ищет) и добавляет в очередь."""
        loading_message = await ctx.send(embed=create_embed("🔄 Загрузка", "Скачиваем трек..."))
        try:
            track = await self._download_track(url_or_search, ctx.author)
            self.queue.append(track)
            file_size = os.path.getsize(track['file']) / (1024 * 1024) if os.path.exists(track['file']) else 0
            position = len(self.queue)
            is_playing = ctx.guild.voice_client and ctx.guild.voice_client.is_playing()
            embed = create_embed(
                "✅ Трек добавлен", f"**[{track['title']}]({track['url']})**", COLORS['SUCCESS'],
                thumbnail=track['thumbnail'],
                fields=[
                    ("Файл", f"`{os.path.basename(track['file'])}` ({file_size:.2f} МБ)", True),
                    ("Длительность", format_duration(track['duration']), True),
                    ("Запросил", track['requester'].mention, True)
                ],
                footer=f"Позиция в очереди: {position}" if position > 0 or is_playing else "Сейчас играет"
            )
            await loading_message.edit(embed=embed)
            self.text_channel = ctx.channel

            if not ctx.guild.voice_client.is_playing() and not self.is_paused:
                await self.play_next(ctx.guild)
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении трека: {e}", exc_info=True)
            await loading_message.edit(embed=create_embed("❌ Ошибка", f"Не удалось добавить трек: {str(e)[:900]}", COLORS['ERROR']))
            return False

    async def _download_track(self, url, requester):
        """Скачивает трек и возвращает информацию о нем."""
        ytdl = yt_dlp.YoutubeDL(YDL_OPTS)
        info = await self.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=True))
        if 'entries' in info: info = info['entries'][0]
        filename = ytdl.prepare_filename(info); base_filename = os.path.splitext(filename)[0]
        audio_file = None
        # Ищем mp3 или opus
        for ext in ['.mp3', '.opus', '.m4a', '.webm']:
            if os.path.exists(f"{base_filename}{ext}"): audio_file = f"{base_filename}{ext}"; logger.info(f"Найден скачанный файл: {audio_file}"); break
        if not audio_file:
            matching_files = glob.glob(f"{base_filename}.*")
            if matching_files: audio_file = matching_files[0]; logger.warning(f"Файл с ожидаемым расширением не найден, используется: {audio_file}")
            else: raise FileNotFoundError(f"Скачанный аудиофайл не найден: {base_filename}.*")
        if os.path.getsize(audio_file) == 0: raise ValueError(f"Скачанный файл имеет нулевой размер: {audio_file}")
        return {'file': audio_file, 'title': info.get('title', 'Unknown title'), 'url': info.get('webpage_url', info.get('url')), 'duration': info.get('duration', 0), 'thumbnail': info.get('thumbnail'), 'requester': requester, 'uploader': info.get('uploader', 'Unknown uploader'), 'uploader_url': info.get('uploader_url'), 'id': info.get('id', '')}

    async def play_next(self, guild: discord.Guild):
        """Воспроизводит следующий трек из очереди."""
        if self.is_playing_next: return
        self.is_playing_next = True
        voice_client = guild.voice_client
        if not voice_client: self.is_playing_next = False; return

        try:
            self.skip_votes.clear()
            if not self.queue:
                if self.now_playing_message:
                    try: await self.now_playing_message.delete()
                    except: pass
                self.now_playing_message = None; self.current = None
                if self.text_channel: await self.text_channel.send(embed=create_embed("🎵 Очередь завершена", "Очередь пуста.", COLORS['DEFAULT']))
                self.is_playing_next = False; return

            track = self.queue.popleft()
            self.current = track
            file_path = self.current['file']
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0: raise FileNotFoundError(f"Файл трека недоступен: {file_path}")

            logger.info(f"Создание FFmpegPCMAudio для: {file_path}")
            try:
                # Возвращаем упрощенные опции и добавляем логирование stderr
                ffmpeg_options = {
                    'options': '-vn',
                    # 'stderr': subprocess.PIPE # Можно раскомментировать для захвата stderr
                }
                audio = discord.FFmpegPCMAudio(file_path, **ffmpeg_options)
                source = discord.PCMVolumeTransformer(audio, volume=self.volume)
                logger.info(f"Аудио источник создан.")
            except Exception as audio_error:
                logger.error(f"Ошибка FFmpegPCMAudio: {audio_error}", exc_info=True)
                if self.text_channel: await self.text_channel.send(embed=create_embed("❌ Ошибка FFmpeg", f"Не удалось обработать аудиофайл.\nОшибка: `{audio_error}`", COLORS['ERROR']))
                raise

            # --- Улучшенный асинхронный callback ---
            async def after_playback_async(error):
                finished_track_path = track.get('file')
                if error:
                    logger.error(f"Ошибка воспроизведения (в callback): {error}")
                    if self.text_channel:
                        await self.text_channel.send(embed=create_embed("❌ Ошибка воспроизведения", f"Произошла ошибка: `{error}`", COLORS['ERROR']))
                else:
                    logger.debug("Трек завершен, планируем следующий.")

                # Удаляем файл завершенного трека
                if finished_track_path and os.path.exists(finished_track_path):
                    try:
                        os.remove(finished_track_path)
                        logger.info(f"Удален файл: {finished_track_path}")
                    except Exception as e:
                        logger.error(f"Не удалось удалить файл {finished_track_path}: {e}")

                # Запускаем следующий трек асинхронно
                asyncio.create_task(self.play_next(guild))

            # --- Обертка для синхронного after ---
            def after_playback_sync(error):
                 # Запускаем асинхронную версию в event loop
                 self.loop.call_soon_threadsafe(asyncio.create_task, after_playback_async(error))


            logger.info(f"Вызов voice_client.play() для трека: {self.current['title']}")
            voice_client.play(source, after=after_playback_sync) # Используем синхронную обертку
            logger.info(f"Воспроизведение трека запущено.")
            self.is_paused = False # Сбрасываем флаг паузы при начале нового трека

            if self.text_channel:
                if self.now_playing_message:
                    try: await self.now_playing_message.delete()
                    except discord.NotFound: pass # Игнорируем, если сообщение уже удалено
                    except Exception as e: logger.warning(f"Не удалось удалить старое сообщение 'Сейчас играет': {e}")
                embed = self._create_now_playing_embed()
                self.view = PlayerControlView(self) # Создаем View
                self.now_playing_message = await self.text_channel.send(embed=embed, view=self.view) # Отправляем с View

        except Exception as e:
            logger.error(f"Ошибка в play_next: {e}", exc_info=True)
            if self.text_channel: await self.text_channel.send(embed=create_embed("❌ Ошибка", f"Ошибка воспроизведения: {e}", COLORS['ERROR']))
            await asyncio.sleep(1)
            asyncio.create_task(self.play_next(guild))
        finally:
            self.is_playing_next = False

    def _create_now_playing_embed(self):
        """Создает эмбед для текущего трека (без футера с loop/shuffle)."""
        if not self.current: return create_embed("Ничего не играет", "Добавьте треки в очередь")
        track = self.current
        fields = [("Длительность", format_duration(track['duration']), True), ("Запросил", track['requester'].mention, True)]
        if track['uploader']: fields.append(("Автор", f"[{track['uploader']}]({track['uploader_url']})" if track['uploader_url'] else track['uploader'], True))
        if self.queue: fields.append((f"Следующий трек ({len(self.queue)})", f"**{self.queue[0]['title']}**", False))
        return create_embed("🎵 Сейчас играет", f"**[{track['title']}]({track['url']})**", COLORS['DEFAULT'], thumbnail=track['thumbnail'], fields=fields)

    # Методы skip, stop, pause, resume, remove, show_queue, search_tracks удалены из класса
    # Они будут реализованы как отдельные handle_* функции

# --- Интерактивные компоненты (Views) ---

class PlayerControlView(discord.ui.View):
    """View с кнопками управления плеером."""
    def __init__(self, player: MusicPlayer, timeout=None): # Убираем авто-таймаут
        super().__init__(timeout=timeout)
        self.player = player
        self._update_buttons()

    def _update_buttons(self):
        """Обновляет состояние кнопок (например, Pause/Resume)."""
        # Находим кнопку паузы/возобновления по custom_id
        pause_resume_button = discord.utils.get(self.children, custom_id="pause_resume")
        if pause_resume_button:
            if self.player.is_paused:
                pause_resume_button.label = "▶️ Resume"
                pause_resume_button.style = discord.ButtonStyle.green
            else:
                pause_resume_button.label = "⏸️ Pause"
                pause_resume_button.style = discord.ButtonStyle.secondary

    async def _handle_interaction(self, interaction: discord.Interaction, handler: Callable):
        """Общий обработчик для кнопок."""
        # Проверяем, что пользователь в том же канале, что и бот (если бот в канале)
        vc = interaction.guild.voice_client
        if vc and interaction.user.voice and interaction.user.voice.channel == vc.channel:
            # Используем контекст из interaction для вызова обработчиков
            # Создаем "фиктивный" контекст, т.к. handle_* ожидают его
            ctx = await self.player.bot.get_context(interaction.message)
            ctx.author = interaction.user # Устанавливаем автора из interaction
            ctx.interaction = interaction # Сохраняем interaction для возможного ответа
            await handler(ctx)
            # Обновляем кнопки после действия
            self._update_buttons()
            # Отвечаем на interaction, чтобы убрать "Interaction Failed"
            try:
                # Используем defer() если handler уже ответил, иначе respond()
                if not interaction.response.is_done():
                     await interaction.response.edit_message(view=self) # Просто обновляем View
            except discord.NotFound: pass # Сообщение могло быть удалено
            except Exception as e: logger.warning(f"Ошибка при обновлении View после нажатия кнопки: {e}")

        else:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)

    @discord.ui.button(label="⏸️ Pause", style=discord.ButtonStyle.secondary, custom_id="pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        handler = handle_resume if self.player.is_paused else handle_pause
        await self._handle_interaction(interaction, handler)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.primary, custom_id="skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_interaction(interaction, handle_skip)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_interaction(interaction, handle_stop)
        # После остановки View больше не нужна
        self.stop() # Останавливает View и удаляет кнопки
        # Попытаемся удалить сообщение "Сейчас играет" после остановки
        try:
            await interaction.message.delete()
        except discord.NotFound: pass
        except Exception as e: logger.warning(f"Не удалось удалить сообщение 'Сейчас играет' после остановки: {e}")

    # Можно добавить кнопку Queue сюда же
    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary, custom_id="queue")
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
         # Для queue не обязательно быть в голосовом канале
         ctx = await self.player.bot.get_context(interaction.message)
         ctx.author = interaction.user
         ctx.interaction = interaction
         # Отправляем очередь как ephemeral сообщение
         await handle_queue(ctx, ephemeral=True)
         # Отвечаем на interaction пустым сообщением, чтобы убрать "Interaction Failed"
         if not interaction.response.is_done():
             await interaction.response.send_message("Очередь показана.", ephemeral=True, delete_after=1)


class SearchResultSelect(discord.ui.Select):
    """Выпадающий список для выбора трека из результатов поиска."""
    def __init__(self, player: MusicPlayer, ctx: commands.Context, entries: List[Dict], original_message: discord.Message):
        self.player = player
        self.ctx = ctx
        self.original_message = original_message
        options = []
        for i, entry in enumerate(entries):
            if entry is None: continue # Пропускаем None значения
            label = entry.get('title', f'Unknown Title {i+1}')
            # Обрезаем слишком длинные названия
            if len(label) > 100: label = label[:97] + "..."
            description = f"By: {entry.get('uploader', 'N/A')} | {format_duration(entry.get('duration', 0))}"
            if len(description) > 100: description = description[:97] + "..."
            options.append(discord.SelectOption(label=label, description=description, value=str(i)))

        if not options:
             # Если нет опций, добавляем заглушку
             options.append(discord.SelectOption(label="Ничего не найдено", value="-1", description="Попробуйте другой запрос"))

        super().__init__(placeholder="Выберите трек для добавления в очередь...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_index = int(self.values[0])
        if selected_index == -1: # Заглушка "Ничего не найдено"
            await interaction.response.edit_message(content="Поиск отменен.", embed=None, view=None)
            return

        # Получаем родительский View, чтобы остановить его
        view = self.view
        if view: view.stop() # Останавливаем View после выбора

        # Получаем выбранный трек из entries (хранится в View)
        selected_entry = view.entries[selected_index]
        url = selected_entry.get('url', selected_entry.get('webpage_url'))

        if not url:
            await interaction.response.edit_message(content="❌ Ошибка: Не удалось получить URL для выбранного трека.", embed=None, view=None)
            return

        # Отвечаем на interaction и затем добавляем трек
        await interaction.response.edit_message(content=f"⏳ Добавляем '{selected_entry.get('title', 'выбранный трек')}'...", embed=None, view=None)
        # Используем исходный контекст ctx для добавления трека
        await self.player.add_track(self.ctx, url)
        # Удаляем исходное сообщение с выбором
        try:
            await self.original_message.delete()
        except discord.NotFound: pass
        except Exception as e: logger.warning(f"Не удалось удалить сообщение с результатами поиска: {e}")


class SearchView(discord.ui.View):
    """View, содержащая выпадающий список результатов поиска."""
    def __init__(self, player: MusicPlayer, ctx: commands.Context, entries: List[Dict], original_message: discord.Message, timeout=60.0):
        super().__init__(timeout=timeout)
        self.player = player
        self.ctx = ctx
        self.entries = entries # Сохраняем entries для доступа из Select
        self.original_message = original_message
        self.add_item(SearchResultSelect(player, ctx, entries, original_message))

    async def on_timeout(self):
        # Удаляем сообщение при тайм-ауте
        try:
            await self.original_message.edit(content="⏱️ Время выбора истекло.", embed=None, view=None)
        except discord.NotFound: pass # Сообщение могло быть удалено
        except Exception as e: logger.warning(f"Не удалось отредактировать сообщение поиска при тайм-ауте: {e}")


# --- Вспомогательные функции и обработчики команд (обновленные) ---

async def ensure_voice(ctx: commands.Context) -> bool:
    """Проверяет и обеспечивает голосовое подключение."""
    # Проверяем автора команды
    if not isinstance(ctx.author, discord.Member): # Может быть вызвано из interaction без member
         await ctx.send(embed=create_embed("❌ Ошибка", "Не удалось определить ваш голосовой канал.", COLORS['ERROR']), ephemeral=True)
         return False
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send(embed=create_embed("❌ Ошибка", "Вы должны быть в голосовом канале", COLORS['ERROR']), ephemeral=True)
        return False

    voice_client = ctx.guild.voice_client
    target_channel = ctx.author.voice.channel

    if not voice_client:
        try:
            logger.info(f"Подключение к каналу: {target_channel.name}")
            await target_channel.connect()
        except asyncio.TimeoutError:
             await ctx.send(embed=create_embed("❌ Ошибка", "Не удалось подключиться к каналу (тайм-аут).", COLORS['ERROR']), ephemeral=True)
             return False
        except Exception as e:
            logger.error(f"Ошибка подключения к {target_channel.name}: {e}", exc_info=True)
            await ctx.send(embed=create_embed("❌ Ошибка", f"Не удалось подключиться: {e}", COLORS['ERROR']), ephemeral=True)
            return False
    elif voice_client.channel != target_channel:
        try:
            logger.info(f"Перемещение в канал: {target_channel.name}")
            await voice_client.move_to(target_channel)
        except asyncio.TimeoutError:
            await ctx.send(embed=create_embed("❌ Ошибка", "Не удалось переместиться в канал (тайм-аут).", COLORS['ERROR']), ephemeral=True)
            return False
        except Exception as e:
            logger.error(f"Ошибка перемещения в {target_channel.name}: {e}", exc_info=True)
            await ctx.send(embed=create_embed("❌ Ошибка", f"Не удалось переместиться: {e}", COLORS['ERROR']), ephemeral=True)
            return False
    return True

async def handle_play(ctx: commands.Context, query: str):
    """Обрабатывает команду воспроизведения."""
    # Отвечаем на interaction как можно скорее, если он есть
    is_interaction = isinstance(ctx, commands.Context) and ctx.interaction is not None
    if is_interaction and not ctx.interaction.response.is_done():
        await ctx.interaction.response.defer(ephemeral=False, thinking=True) # Показываем "Bot is thinking..."

    if not query:
        await ctx.send(embed=create_embed("❌ Ошибка", "Укажите запрос или ссылку", COLORS['ERROR']), ephemeral=True)
        return
    if not await ensure_voice(ctx):
        # ensure_voice уже отправил сообщение об ошибке
        return

    player = getattr(ctx.cog, 'player', None) # Получаем плеер из кога
    if not player:
        await ctx.send("Ошибка: Экземпляр плеера не найден.", ephemeral=True)
        return

    # Устанавливаем текстовый канал для будущих сообщений плеера
    if not player.text_channel:
        player.text_channel = ctx.channel
        logger.info(f"Текстовый канал для плеера установлен: {ctx.channel.name} ({ctx.channel.id})")


    if query.startswith(('http://', 'https://')):
        # Если это ссылка, просто добавляем трек
        # Сообщение о загрузке/добавлении будет внутри add_track
        await player.add_track(ctx, query)
    else:
        # Если это поисковый запрос, вызываем search_tracks
        await search_tracks(ctx, query, player)

async def search_tracks(ctx: commands.Context, query: str, player: MusicPlayer, max_results=10):
    """Ищет треки и показывает результаты с помощью discord.ui.Select."""
    # Если это interaction, используем follow-up, иначе редактируем или отправляем новое
    is_interaction = isinstance(ctx, commands.Context) and ctx.interaction is not None
    send_method = ctx.interaction.followup.send if is_interaction else ctx.send

    # Отправляем сообщение о поиске
    search_message = await send_method(embed=create_embed("🔍 Поиск", f"Ищу `{query}`..."), wait=True if is_interaction else False)
    edit_method = search_message.edit

    try:
        # Используем yt-dlp для поиска без скачивания
        search_opts = YDL_OPTS.copy()
        search_opts['extract_flat'] = 'in_playlist' # Получаем плоский список URL и метаданных
        search_opts['playlistend'] = max_results # Ограничиваем количество результатов
        search_opts['quiet'] = True
        search_opts['ignoreerrors'] = True # Игнорируем ошибки отдельных видео в плейлисте/поиске

        ytdl = yt_dlp.YoutubeDL(search_opts)
        # Используем ytsearch: для явного поиска на YouTube
        info = await player.loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch{max_results}:{query}", download=False))

        if not info or not info.get('entries'):
            await edit_method(embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` ничего не найдено.", COLORS['ERROR']))
            return

        # Фильтруем результаты, оставляя только словари с 'url'
        valid_entries = [entry for entry in info['entries'] if isinstance(entry, dict) and entry.get('url')]

        if not valid_entries:
            await edit_method(embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` нет доступных результатов.", COLORS['ERROR']))
            return

        # Создаем View с выпадающим списком
        view = SearchView(player, ctx, valid_entries, search_message)
        embed = create_embed(f"🔍 Результаты поиска для '{query}'", "Выберите трек из списка ниже:")
        await edit_method(embed=embed, view=view)

    except yt_dlp.utils.DownloadError as e:
         logger.warning(f"Ошибка yt-dlp при поиске '{query}': {e}")
         await edit_method(embed=create_embed("❌ Ошибка поиска", f"Не удалось выполнить поиск. Возможно, проблема с YouTube или yt-dlp.\n`{e}`", COLORS['ERROR']))
    except Exception as e:
        logger.error(f"Неизвестная ошибка при поиске треков '{query}': {e}", exc_info=True)
        await edit_method(embed=create_embed("❌ Ошибка", f"Произошла неизвестная ошибка при поиске:\n`{e}`", COLORS['ERROR']))


async def handle_skip(ctx: commands.Context):
    """Пропускает текущий трек."""
    is_interaction = isinstance(ctx, commands.Context) and ctx.interaction is not None
    send_method = ctx.interaction.response.send_message if is_interaction else ctx.send
    player = getattr(ctx.cog, 'player', None)
    if not player or not player.current or not ctx.guild.voice_client or not ctx.guild.voice_client.is_playing():
        await send_method(embed=create_embed("❌ Ошибка", "Сейчас ничего не воспроизводится.", COLORS['ERROR']), ephemeral=True)
        return

    # Проверяем права (DJ или запросивший)
    is_dj = isinstance(ctx.author, discord.Member) and any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
    is_requester = player.current and player.current['requester'].id == ctx.author.id

    if is_dj or is_requester:
        await send_method(embed=create_embed("⏭️ Трек пропущен", f"Трек **{player.current['title']}** пропущен по запросу {ctx.author.mention}.", COLORS['SUCCESS']))
        ctx.guild.voice_client.stop() # Останавливаем воспроизведение, after_playback запустит следующий
        player.skip_votes.clear() # Очищаем голоса после пропуска
        return

    # --- Логика голосования ---
    # Считаем только людей в канале
    channel_members = len([m for m in ctx.guild.voice_client.channel.members if not m.bot])
    required_votes = math.ceil(channel_members / 2) if channel_members > 1 else 1 # Нужно хотя бы 1 голос, если бот не один

    if ctx.author.id in player.skip_votes:
        await send_method(embed=create_embed("⏭️ Голосование", f"Вы уже голосовали за пропуск!\nГолосов: {len(player.skip_votes)}/{required_votes}", COLORS['DEFAULT']), ephemeral=True)
        return

    player.skip_votes.add(ctx.author.id)
    current_votes = len(player.skip_votes)

    if current_votes >= required_votes:
        await send_method(embed=create_embed("⏭️ Трек пропущен", f"Трек **{player.current['title']}** пропущен по голосованию ({current_votes}/{required_votes}).", COLORS['SUCCESS']))
        ctx.guild.voice_client.stop()
        player.skip_votes.clear() # Очищаем голоса
    else:
        await send_method(embed=create_embed("⏭️ Голосование", f"{ctx.author.mention} проголосовал(а) за пропуск.\nГолосов: {current_votes}/{required_votes}", COLORS['DEFAULT']))


async def handle_stop(ctx: commands.Context):
    """Останавливает воспроизведение, очищает очередь и отключается."""
    is_interaction = isinstance(ctx, commands.Context) and ctx.interaction is not None
    send_method = ctx.interaction.response.send_message if is_interaction else ctx.send
    player = getattr(ctx.cog, 'player', None)
    if not player or not ctx.guild.voice_client:
        await send_method(embed=create_embed("❌ Ошибка", "Бот не находится в голосовом канале.", COLORS['ERROR']), ephemeral=True)
        return

    logger.info(f"Команда stop вызвана пользователем {ctx.author}")
    # Сохраняем текущее сообщение "Now Playing" для возможного удаления
    now_playing_msg = player.now_playing_message

    # Очищаем очередь и состояние плеера ДО отключения
    await cleanup_player(player, ctx.guild.name) # Используем общую функцию очистки

    # Останавливаем воспроизведение, если оно идет
    if ctx.guild.voice_client.is_playing() or ctx.guild.voice_client.is_paused():
        logger.info("Остановка voice_client...")
        ctx.guild.voice_client.stop() # Это прервет текущий трек

    # Отключаемся от канала
    logger.info("Отключение от голосового канала...")
    await ctx.guild.voice_client.disconnect()

    # Удаляем сообщение "Now Playing", если оно было и interaction не удалил его сам
    if now_playing_msg and not is_interaction: # Не удаляем, если это interaction, т.к. View сама удалит
         try:
             await now_playing_msg.delete()
             logger.info("Сообщение 'Now Playing' удалено после команды stop.")
         except discord.NotFound: pass
         except Exception as e: logger.warning(f"Не удалось удалить сообщение 'Now Playing' после stop: {e}")

    # Отправляем подтверждение
    await send_method(embed=create_embed("⏹️ Остановлено", "Воспроизведение остановлено, очередь очищена, бот отключен.", COLORS['SUCCESS']), ephemeral=is_interaction) # Ephemeral для interaction


async def handle_pause(ctx: commands.Context):
    """Ставит воспроизведение на паузу."""
    is_interaction = isinstance(ctx, commands.Context) and ctx.interaction is not None
    send_method = ctx.interaction.response.send_message if is_interaction else ctx.send
    player = getattr(ctx.cog, 'player', None)
    if not player or not ctx.guild.voice_client or not ctx.guild.voice_client.is_playing():
        await send_method(embed=create_embed("❌ Ошибка", "Сейчас ничего не воспроизводится.", COLORS['ERROR']), ephemeral=True)
        return
    if ctx.guild.voice_client.is_paused():
        await send_method(embed=create_embed("ℹ️ Инфо", "Воспроизведение уже на паузе.", COLORS['DEFAULT']), ephemeral=True)
        return

    ctx.guild.voice_client.pause()
    player.is_paused = True
    await send_method(embed=create_embed("⏸️ Пауза", "Воспроизведение приостановлено.", COLORS['DEFAULT']), ephemeral=is_interaction) # Ephemeral для interaction


async def handle_resume(ctx: commands.Context):
    """Возобновляет воспроизведение."""
    is_interaction = isinstance(ctx, commands.Context) and ctx.interaction is not None
    send_method = ctx.interaction.response.send_message if is_interaction else ctx.send
    player = getattr(ctx.cog, 'player', None)
    if not player or not ctx.guild.voice_client or not ctx.guild.voice_client.is_paused():
        await send_method(embed=create_embed("❌ Ошибка", "Воспроизведение не приостановлено.", COLORS['ERROR']), ephemeral=True)
        return

    ctx.guild.voice_client.resume()
    player.is_paused = False
    await send_method(embed=create_embed("▶️ Продолжение", "Воспроизведение возобновлено.", COLORS['SUCCESS']), ephemeral=is_interaction) # Ephemeral для interaction


async def handle_remove(ctx: commands.Context, position: int):
    """Удаляет трек из очереди по позиции."""
    is_interaction = isinstance(ctx, commands.Context) and ctx.interaction is not None
    send_method = ctx.interaction.response.send_message if is_interaction else ctx.send
    player = getattr(ctx.cog, 'player', None)
    if not player or not player.queue:
        await send_method(embed=create_embed("❌ Ошибка", "Очередь пуста.", COLORS['ERROR']), ephemeral=True)
        return

    queue_len = len(player.queue)
    if not (1 <= position <= queue_len):
        await send_method(embed=create_embed("❌ Ошибка", f"Неверный номер трека. Укажите номер от 1 до {queue_len}.", COLORS['ERROR']), ephemeral=True)
        return

    try:
        # Преобразуем deque в список для индексации
        queue_list = list(player.queue)
        track_to_remove = queue_list[position - 1]

        # Проверяем права (DJ или запросивший)
        is_dj = isinstance(ctx.author, discord.Member) and any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
        is_requester = track_to_remove['requester'].id == ctx.author.id

        if not (is_dj or is_requester):
            await send_method(embed=create_embed("❌ Ошибка доступа", "Удалить трек из очереди может только DJ или пользователь, который его добавил.", COLORS['ERROR']), ephemeral=True)
            return

        # Удаляем элемент из оригинального deque по значению (менее эффективно, но проще чем пересоздавать deque)
        # Важно: это сработает корректно, только если в очереди нет абсолютно одинаковых треков (что маловероятно)
        # Более надежный способ - пересоздать deque без удаленного элемента.
        # del player.queue[position - 1] # Так нельзя с deque
        new_queue = deque(item for i, item in enumerate(queue_list) if i != position - 1)
        player.queue = new_queue

        await send_method(embed=create_embed("🗑️ Трек удален", f"Трек **{track_to_remove['title']}** (позиция {position}) удален из очереди.", COLORS['SUCCESS']))

        # Удаляем файл, если он больше не нужен (проверяем, есть ли он еще где-то в очереди)
        file_to_check = track_to_remove.get('file')
        if file_to_check and os.path.exists(file_to_check):
            is_file_still_in_queue = any(track.get('file') == file_to_check for track in player.queue)
            if not is_file_still_in_queue:
                try:
                    os.remove(file_to_check)
                    logger.info(f"Удален файл удаленного из очереди трека: {file_to_check}")
                except Exception as e:
                    logger.error(f"Не удалось удалить файл {file_to_check} после удаления из очереди: {e}")

    except IndexError: # Это не должно произойти из-за проверки выше, но на всякий случай
        await send_method(embed=create_embed("❌ Ошибка", "Неверный номер позиции в очереди.", COLORS['ERROR']), ephemeral=True)
    except Exception as e:
        logger.error(f"Ошибка при удалении трека из очереди: {e}", exc_info=True)
        await send_method(embed=create_embed("❌ Ошибка", f"Произошла ошибка при удалении трека: {e}", COLORS['ERROR']), ephemeral=True)


async def handle_queue(ctx: commands.Context, ephemeral: bool = False):
    """Показывает очередь воспроизведения."""
    is_interaction = isinstance(ctx, commands.Context) and ctx.interaction is not None
    send_method = ctx.interaction.response.send_message if is_interaction and ephemeral else (ctx.interaction.followup.send if is_interaction else ctx.send)
    player = getattr(ctx.cog, 'player', None)
    if not player or (not player.queue and not player.current):
        await send_method(embed=create_embed("ℹ️ Очередь пуста", "Сейчас ничего не играет и очередь пуста.", COLORS['DEFAULT']), ephemeral=ephemeral)
        return

    embed = discord.Embed(title="🎵 Очередь воспроизведения", color=COLORS['DEFAULT'])
    description_lines = []

    if player.current:
        state = "⏸️" if player.is_paused else "▶️"
        description_lines.append(f"**{state} Сейчас играет:**")
        description_lines.append(f"[{player.current['title']}]({player.current['url']}) | `{format_duration(player.current['duration'])}` | Запросил: {player.current['requester'].mention}")
        description_lines.append("") # Пустая строка для разделения

    if player.queue:
        description_lines.append("**⏱️ В очереди:**")
        queue_list = list(player.queue)
        for i, track in enumerate(queue_list[:15], 1): # Показываем до 15 треков
            description_lines.append(f"`{i}.` [{track['title']}]({track['url']}) | `{format_duration(track['duration'])}` | {track['requester'].mention}")
        if len(queue_list) > 15:
            description_lines.append(f"\n*...и еще {len(queue_list) - 15} трек(ов)*")
    elif not player.current: # Если current нет и queue пуста (на всякий случай)
         description_lines.append("Очередь пуста.")


    embed.description = "\n".join(description_lines)[:4096] # Ограничение длины описания
    embed.set_footer(text=f"Всего треков: {len(player.queue) + (1 if player.current else 0)}")

    await send_method(embed=embed, ephemeral=ephemeral)


# Функции cleanup_player и auto_disconnect используются внутренне и в event handler
async def cleanup_player(player: MusicPlayer, guild_name: str):
    """Очищает состояние плеера, удаляет временные файлы и View."""
    if not player: logger.warning("Попытка очистить несуществующий плеер."); return
    logger.info(f"Начало очистки плеера для {guild_name}...")
    # Останавливаем View, если она активна
    if player.view:
        player.view.stop()
        player.view = None

    # Удаляем сообщение "Now Playing", если оно есть
    if player.now_playing_message:
        try:
            await player.now_playing_message.delete()
            logger.info("Сообщение 'Now Playing' удалено при очистке.")
        except discord.NotFound: pass # Уже удалено
        except Exception as e: logger.warning(f"Не удалось удалить сообщение 'Now Playing' при очистке: {e}")
        player.now_playing_message = None

    # Собираем все уникальные пути к файлам из текущего трека и очереди
    files_to_delete = set()
    if player.current and player.current.get('file'):
        files_to_delete.add(player.current['file'])
    for track in player.queue:
        if track.get('file'):
            files_to_delete.add(track['file'])

    # Очищаем состояние плеера
    player.queue.clear()
    player.current = None
    player.is_paused = False
    player.skip_votes.clear()
    player.text_channel = None # Сбрасываем канал

    # Удаляем собранные файлы
    for file_path in files_to_delete:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Удален файл при очистке: {file_path}")
            except Exception as e:
                logger.error(f"Не удалось удалить файл {file_path} при очистке: {e}")

    logger.info(f"Плеер успешно очищен для сервера {guild_name}")


async def auto_disconnect(player: MusicPlayer, guild: discord.Guild, voice_channel: discord.VoiceChannel):
    """Автоматически отключает бота, если он остался один в канале."""
    if not player: logger.warning(f"Попытка автоотключения для несуществующего плеера в {guild.name}"); return
    if player.text_channel:
        try: await player.text_channel.send(embed=create_embed("👋 Автоотключение", "Все ушли, бот отключается.", COLORS['DEFAULT']))
        except Exception as e: logger.error(f"Ошибка при отправке сообщения об автоотключении: {e}")
    try:
        if guild.voice_client: await guild.voice_client.disconnect()
    except Exception as e: logger.error(f"Ошибка при отключении от голосового канала: {e}")
    await cleanup_player(player, guild.name) # Вызываем cleanup_player здесь
    logger.info(f"Бот автоматически отключен от канала {voice_channel.name}")
