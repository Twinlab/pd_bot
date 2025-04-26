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

            # --- Возвращаем старый синхронный callback с блокирующим future.result() ---
            def after_playback(error):
                finished_track_path = track.get('file')
                if error:
                    logger.error(f"Ошибка воспроизведения (в callback): {error}")
                else:
                    logger.debug("Трек завершен, планируем следующий.")

                # Планируем запуск следующего трека
                future = asyncio.run_coroutine_threadsafe(self.play_next(guild), self.loop)
                try:
                    future.result(timeout=30) # Блокирующее ожидание
                except Exception as e:
                    logger.error(f"Ошибка при ожидании/запуске play_next из after_playback: {e}")

                # Удаляем файл
                if finished_track_path and os.path.exists(finished_track_path):
                    try: os.remove(finished_track_path); logger.info(f"Удален файл: {finished_track_path}")
                    except Exception as e: logger.error(f"Не удалось удалить файл {finished_track_path}: {e}")

            logger.info(f"Вызов voice_client.play() для трека: {self.current['title']}")
            voice_client.play(source, after=after_playback)
            logger.info(f"Воспроизведение трека запущено.")

            if self.text_channel:
                if self.now_playing_message:
                    try: await self.now_playing_message.delete()
                    except: pass
                embed = self._create_now_playing_embed()
                self.now_playing_message = await self.text_channel.send(embed=embed) # Отправляем без View

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

# --- Вспомогательные функции и обработчики команд (старая структура) ---

async def ensure_voice(ctx):
    """Проверяет и обеспечивает голосовое подключение."""
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send(embed=create_embed("❌ Ошибка", "Вы должны быть в голосовом канале", COLORS['ERROR']))
        return False
    voice_client = ctx.guild.voice_client
    if not voice_client:
        try: await ctx.author.voice.channel.connect()
        except Exception as e: await ctx.send(embed=create_embed("❌ Ошибка", f"Не удалось подключиться: {e}", COLORS['ERROR'])); return False
    elif voice_client.channel != ctx.author.voice.channel:
        try: await voice_client.move_to(ctx.author.voice.channel)
        except Exception as e: await ctx.send(embed=create_embed("❌ Ошибка", f"Не удалось переместиться: {e}", COLORS['ERROR'])); return False
    return True

async def handle_play(ctx, query):
    """Обрабатывает команду воспроизведения."""
    if not query: await ctx.send(embed=create_embed("❌ Ошибка", "Укажите запрос или ссылку", COLORS['ERROR'])); return
    if not await ensure_voice(ctx): return

    player = getattr(ctx.cog, 'player', None) # Получаем плеер из кога
    if not player: await ctx.send("Ошибка: Экземпляр плеера не найден."); return

    if query.startswith(('http://', 'https://')):
        await player.add_track(ctx, query)
    else:
        await search_tracks(ctx, query, player) # Вызываем search_tracks

async def search_tracks(ctx, query, player: MusicPlayer, max_results=5):
    """Ищет треки и позволяет выбрать (вызывается из handle_play)."""
    loading_message = await ctx.send(embed=create_embed("🔍 Поиск", f"Ищу `{query}`..."))
    try:
        search_opts = YDL_OPTS.copy(); search_opts['default_search'] = f'ytsearch{max_results}'; search_opts['extract_flat'] = True; search_opts['quiet'] = True
        ytdl = yt_dlp.YoutubeDL(search_opts)
        info = await player.loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch{max_results}:{query}", download=False))
        if not info or not info.get('entries'): await loading_message.edit(embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` ничего не найдено", COLORS['ERROR'])); return
        valid_entries = [entry for entry in info['entries'] if entry is not None]
        if not valid_entries: await loading_message.edit(embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` нет доступных результатов", COLORS['ERROR'])); return
        description = "Выберите трек, отправив его номер (или 'отмена'):"; fields = []
        for i, entry in enumerate(valid_entries, 1): fields.append((f"{i}. {entry.get('title', 'Неизвестно')}", f"Автор: {entry.get('uploader', 'Неизвестно')} | Длительность: {format_duration(entry.get('duration', 0))}", False))
        await loading_message.edit(embed=create_embed(f"🔍 Результаты поиска '{query}'", description, fields=fields))
        try:
            response = await player.bot.wait_for('message', check=lambda m: (m.author == ctx.author and m.channel == ctx.channel and (m.content.lower() in ['отмена', 'cancel'] or (m.content.isdigit() and 1 <= int(m.content) <= len(valid_entries)))), timeout=30)
            if response.content.lower() in ['отмена', 'cancel']: await ctx.send(embed=create_embed("🚫 Отменено", "Поиск отменен", COLORS['DEFAULT'])); return
            choice = int(response.content) - 1; selected = valid_entries[choice]
            url = selected.get('url', selected.get('webpage_url'))
            if not url: await ctx.send(embed=create_embed("❌ Ошибка", "Не удалось получить URL", COLORS['ERROR'])); return
            await player.add_track(ctx, url) # Вызываем add_track плеера
        except asyncio.TimeoutError: await ctx.send(embed=create_embed("⏱️ Время истекло", "Вы не выбрали трек", COLORS['ERROR']))
    except Exception as e: logger.error(f"Ошибка при поиске треков: {e}", exc_info=True); await loading_message.edit(embed=create_embed("❌ Ошибка", f"Ошибка при поиске: {str(e)[:900]}", COLORS['ERROR']))

async def handle_skip(ctx):
    """Пропускает текущий трек."""
    player = getattr(ctx.cog, 'player', None)
    if not player or not player.voice_client or not player.voice_client.is_playing(): await ctx.send(embed=create_embed("❌ Ошибка", "Ничего не воспроизводится", COLORS['ERROR'])); return
    is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
    is_requester = player.current and player.current['requester'].id == ctx.author.id
    if is_dj or is_requester: await ctx.send(embed=create_embed("⏭️ Трек пропущен", f"Трек пропущен по запросу {ctx.author.mention}", COLORS['SUCCESS'])); player.voice_client.stop(); return
    channel_members = len([m for m in player.voice_client.channel.members if not m.bot]); required_votes = math.ceil(channel_members / 2)
    if ctx.author.id in player.skip_votes: await ctx.send(embed=create_embed("⏭️ Голосование", f"Вы уже голосовали!\nГолосов: {len(player.skip_votes)}/{required_votes}", COLORS['DEFAULT'])); return
    player.skip_votes.add(ctx.author.id)
    if len(player.skip_votes) >= required_votes: await ctx.send(embed=create_embed("⏭️ Трек пропущен", f"Трек пропущен по голосованию ({len(player.skip_votes)}/{required_votes})", COLORS['SUCCESS'])); player.voice_client.stop()
    else: await ctx.send(embed=create_embed("⏭️ Голосование", f"{ctx.author.mention} проголосовал за пропуск\nГолосов: {len(player.skip_votes)}/{required_votes}", COLORS['DEFAULT']))

async def handle_stop(ctx):
    """Останавливает воспроизведение и очищает очередь."""
    player = getattr(ctx.cog, 'player', None)
    if not player or not player.voice_client: await ctx.send(embed=create_embed("❌ Ошибка", "Бот не в голосовом канале", COLORS['ERROR'])); return
    player.queue.clear(); player.is_paused = False
    if player.voice_client.is_playing() or player.voice_client.is_paused(): player.voice_client.stop()
    await player.voice_client.disconnect()
    if player.current and player.current.get('file') and os.path.exists(player.current['file']):
         try: os.remove(player.current['file']); logger.info(f"Удален файл при остановке: {player.current['file']}")
         except Exception as e: logger.error(f"Не удалось удалить файл {player.current['file']} при остановке: {e}")
    if player.now_playing_message:
        try: await player.now_playing_message.delete()
        except: pass
    player.now_playing_message = None; player.current = None; player.skip_votes.clear()
    await ctx.send(embed=create_embed("⏹️ Остановлено", "Воспроизведение остановлено.", COLORS['SUCCESS']))

async def handle_pause(ctx):
    """Ставит воспроизведение на паузу."""
    player = getattr(ctx.cog, 'player', None)
    if not player or not player.voice_client or not player.voice_client.is_playing(): await ctx.send(embed=create_embed("❌ Ошибка", "Нет активного воспроизведения", COLORS['ERROR'])); return
    if player.voice_client.is_paused(): await ctx.send(embed=create_embed("ℹ️ Инфо", "Уже на паузе", COLORS['DEFAULT'])); return
    player.voice_client.pause(); player.is_paused = True
    await ctx.send(embed=create_embed("⏸️ Пауза", "Воспроизведение приостановлено", COLORS['DEFAULT']))

async def handle_resume(ctx):
    """Возобновляет воспроизведение."""
    player = getattr(ctx.cog, 'player', None)
    if not player or not player.voice_client or not player.voice_client.is_paused(): await ctx.send(embed=create_embed("❌ Ошибка", "Воспроизведение не на паузе", COLORS['ERROR'])); return
    player.voice_client.resume(); player.is_paused = False
    await ctx.send(embed=create_embed("▶️ Продолжение", "Воспроизведение возобновлено", COLORS['SUCCESS']))

async def handle_remove(ctx, position):
    """Удаляет трек из очереди по позиции."""
    player = getattr(ctx.cog, 'player', None)
    if not player or not player.queue: await ctx.send(embed=create_embed("❌ Ошибка", "Очередь пуста", COLORS['ERROR'])); return
    if not (1 <= position <= len(player.queue)): await ctx.send(embed=create_embed("❌ Ошибка", f"Позиция от 1 до {len(player.queue)}", COLORS['ERROR'])); return
    try:
        track_to_remove = list(player.queue)[position - 1]
        is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
        is_requester = track_to_remove['requester'].id == ctx.author.id
        if not (is_dj or is_requester): await ctx.send(embed=create_embed("❌ Ошибка", "Удалить может только DJ или запросивший", COLORS['ERROR'])); return
        del player.queue[position - 1]
        await ctx.send(embed=create_embed("🗑️ Трек удален", f"Трек **{track_to_remove['title']}** удален", COLORS['SUCCESS']))
    except IndexError: await ctx.send(embed=create_embed("❌ Ошибка", "Неверная позиция", COLORS['ERROR']))
    except Exception as e: logger.error(f"Ошибка при удалении трека: {e}", exc_info=True); await ctx.send(embed=create_embed("❌ Ошибка", f"Не удалось удалить: {e}", COLORS['ERROR']))

async def handle_queue(ctx):
    """Показывает очередь воспроизведения."""
    player = getattr(ctx.cog, 'player', None)
    if not player or (not player.queue and not player.current): await ctx.send(embed=create_embed("Очередь пуста", "Добавьте треки", COLORS['ERROR'])); return
    description = []
    if player.current: desc = f"**🎵 Сейчас играет:**\n[{player.current['title']}]({player.current['url']}) | {format_duration(player.current['duration'])} | {player.current['requester'].mention}\n"; description.append(desc)
    if player.queue:
        description.append("**⏱️ В очереди:**")
        for i, track in enumerate(list(player.queue)[:10], 1): desc = f"{i}. [{track['title']}]({track['url']}) | {format_duration(track['duration'])} | {track['requester'].mention}"; description.append(desc)
        if len(player.queue) > 10: description.append(f"\n*...и еще {len(player.queue) - 10} трек(ов)*")
    await ctx.send(embed=create_embed("🎵 Очередь воспроизведения", "\n".join(description), footer=f"Всего треков: {len(player.queue) + (1 if player.current else 0)}"))

# Функции cleanup_player и auto_disconnect возвращены для использования в handlers/events.py
async def cleanup_player(player: MusicPlayer, guild_name: str):
    """Очищает состояние плеера."""
    if not player: logger.warning("Попытка очистить несуществующий плеер."); return
    if player.current and player.current.get('file') and os.path.exists(player.current['file']):
         try: os.remove(player.current['file']); logger.info(f"Удален файл при очистке: {player.current['file']}")
         except Exception as e: logger.error(f"Не удалось удалить файл {player.current['file']} при очистке: {e}")
    player.queue.clear(); player.current = None; player.is_paused = False
    if player.now_playing_message:
        try: await player.now_playing_message.delete()
        except: pass
        player.now_playing_message = None
    logger.info(f"Плеер очищен для сервера {guild_name}")

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
