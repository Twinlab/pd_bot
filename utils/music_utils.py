import discord
import asyncio
import logging
import os
import math
import yt_dlp
import json
from collections import deque
import glob
from typing import Dict, List, Optional, Set, Any, Union, Callable
import subprocess # Добавлено для stderr FFmpeg

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
    'format': 'bestaudio/best', # Предпочитаем лучший аудио формат
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
    # Настройки постпроцессора FFmpeg: пробуем Opus
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus', # Изменено с 'mp3' на 'opus'
        'preferredquality': '128', # Качество для Opus (может быть другим)
    }],
    # 'verbose': True, # Раскомментировать для отладки yt-dlp
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
    """Управляет состоянием воспроизведения музыки."""
    def __init__(self, bot):
        self.bot = bot
        self.queue = deque()
        self.current = None
        self.volume = 0.5
        self.text_channel = None
        self.now_playing_message = None
        self.skip_votes = set()
        self.loop = asyncio.get_event_loop()
        self.is_playing_next = False
        self.is_paused = False

    async def send_embed(self, ctx, title, description, color=COLORS['DEFAULT'], **kwargs):
        return await ctx.send(embed=create_embed(title, description, color, **kwargs))

    async def add_track(self, ctx, url_or_search):
        """Добавляет трек в очередь."""
        loading_message = await self.send_embed(ctx, "🔄 Загрузка", "Скачиваем трек...")
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
                footer=f"Позиция в очереди: {position}" if position > 1 or (position == 1 and is_playing) else None
            )
            await loading_message.edit(embed=embed)
            self.text_channel = ctx.channel
            voice_client = ctx.guild.voice_client
            if not voice_client or not voice_client.is_playing():
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

        filename = ytdl.prepare_filename(info)
        base_filename = os.path.splitext(filename)[0]

        # Ищем файл с расширением opus или mp3 (на всякий случай)
        audio_file = None
        for ext in ['.opus', '.mp3', '.m4a', '.webm']: # Opus первый
            if os.path.exists(f"{base_filename}{ext}"):
                audio_file = f"{base_filename}{ext}"
                logger.info(f"Найден скачанный файл: {audio_file}")
                break

        if not audio_file:
            matching_files = glob.glob(f"{base_filename}.*")
            if matching_files:
                audio_file = matching_files[0]
                logger.warning(f"Файл с ожидаемым расширением не найден, используется найденный через glob: {audio_file}")
            else:
                 raise FileNotFoundError(f"Скачанный аудиофайл не найден: {base_filename}.*")

        if os.path.getsize(audio_file) == 0:
            raise ValueError(f"Скачанный файл имеет нулевой размер: {audio_file}")

        return {
            'file': audio_file, 'title': info.get('title', 'Unknown title'),
            'url': info.get('webpage_url', info.get('url')), 'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail'), 'requester': requester,
            'uploader': info.get('uploader', 'Unknown uploader'), 'uploader_url': info.get('uploader_url'),
            'id': info.get('id', '')
        }

    async def play_next(self, guild):
        """Воспроизводит следующий трек из очереди."""
        if self.is_playing_next: return
        self.is_playing_next = True
        try:
            self.skip_votes.clear()
            voice_client = guild.voice_client
            if not voice_client:
                self.is_playing_next = False
                return

            if not self.queue:
                if self.now_playing_message:
                    try: await self.now_playing_message.delete()
                    except: pass
                self.now_playing_message = None
                self.current = None
                if self.text_channel:
                    await self.text_channel.send(embed=create_embed("🎵 Очередь завершена", "Очередь пуста.", COLORS['DEFAULT']))
                self.is_playing_next = False
                return

            track = self.queue.popleft()
            self.current = track
            file_path = track['file']
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise FileNotFoundError(f"Файл трека недоступен или поврежден: {file_path}")

            logger.info(f"Создание FFmpegPCMAudio для файла: {file_path}")
            try:
                # Упрощенные опции FFmpeg + перенаправление stderr
                ffmpeg_options = {
                    'options': '-vn -loglevel warning', # -vn игнорирует видео, -loglevel warning для вывода ошибок
                    # 'stderr': subprocess.PIPE # Перенаправляем stderr FFmpeg
                }
                audio = discord.FFmpegPCMAudio(file_path, **ffmpeg_options)
                source = discord.PCMVolumeTransformer(audio, volume=self.volume)
                logger.info(f"Аудио источник FFmpegPCMAudio создан успешно.")
            except Exception as audio_error:
                logger.error(f"Ошибка при создании FFmpegPCMAudio: {audio_error}", exc_info=True)
                if self.text_channel:
                    await self.text_channel.send(embed=create_embed("❌ Ошибка FFmpeg", f"Не удалось обработать аудиофайл.\nОшибка: `{audio_error}`", COLORS['ERROR']))
                raise

            async def after_playback(error):
                finished_track_path = track.get('file')
                if error:
                    # Логируем ошибку, которая пришла в callback
                    logger.error(f"Ошибка во время воспроизведения (в callback after_playback): {error}")
                    # Дополнительно проверим код завершения процесса FFmpeg, если он доступен
                    if isinstance(source, discord.FFmpegPCMAudio) and hasattr(source, '_process') and source._process:
                         return_code = source._process.returncode
                         logger.error(f"Процесс FFmpeg завершился с кодом: {return_code}")
                         # Можно добавить отправку сообщения об ошибке в чат
                         if self.text_channel:
                              await self.text_channel.send(embed=create_embed("❌ Ошибка воспроизведения", f"FFmpeg завершился с ошибкой (код: {return_code}). Проверьте логи.", COLORS['ERROR']))
                         # Не запускаем следующий трек при ошибке FFmpeg
                         # await asyncio.sleep(1) # Задержка перед удалением не нужна, если не играем дальше
                         # Удаляем файл сразу
                         if finished_track_path and os.path.exists(finished_track_path):
                              try:
                                   os.remove(finished_track_path)
                                   logger.info(f"Удален файл после ошибки воспроизведения: {finished_track_path}")
                              except Exception as delete_error:
                                   logger.error(f"Не удалось удалить файл {finished_track_path} после ошибки: {delete_error}")
                         self.is_playing_next = False # Сбрасываем флаг, т.к. следующий трек не запускаем
                         return # Прерываем выполнение callback

                # Если ошибки не было, запускаем следующий трек
                logger.debug("after_playback: Ошибки нет, запускаем следующий трек.")
                future = asyncio.run_coroutine_threadsafe(self.play_next(guild), self.loop)
                try:
                    future.result(timeout=30)
                except Exception as e:
                    logger.error(f"Ошибка при ожидании запуска play_next из after_playback: {e}")
                finally:
                    # Удаляем файл успешно воспроизведенного трека
                    # await asyncio.sleep(1) # Убираем задержку
                    if finished_track_path and os.path.exists(finished_track_path):
                        try:
                            os.remove(finished_track_path)
                            logger.info(f"Удален файл после успешного воспроизведения: {finished_track_path}")
                        except Exception as delete_error:
                            logger.error(f"Не удалось удалить файл {finished_track_path} после успешного воспроизведения: {delete_error}")

            logger.info(f"Вызов voice_client.play() для трека: {track.get('title', 'Unknown')}")
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(after_playback(e), self.loop).result())
            logger.info(f"Воспроизведение трека запущено.")

            if self.text_channel:
                if self.now_playing_message:
                    try: await self.now_playing_message.delete()
                    except: pass
                embed = self._create_now_playing_embed()
                self.now_playing_message = await self.text_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Ошибка при воспроизведении (внешний try...except): {e}", exc_info=True)
            if self.text_channel:
                await self.text_channel.send(embed=create_embed("❌ Ошибка", f"Ошибка воспроизведения: {str(e)[:900]}", COLORS['ERROR']))
            await asyncio.sleep(1)
            asyncio.create_task(self.play_next(guild))
        finally:
            # Этот флаг должен сбрасываться только если play_next завершился *без* успешного запуска play()
            # Но т.к. play() запускается асинхронно, сложно отследить.
            # Оставляем сброс здесь, но имеем в виду, что он может сброситься до фактического начала игры.
            # Если будут проблемы с параллельным запуском, нужно будет пересмотреть.
            self.is_playing_next = False # Сбрасываем флаг в любом случае

    def _create_now_playing_embed(self):
        """Создает эмбед для текущего трека"""
        if not self.current: return create_embed("Ничего не играет", "Добавьте треки в очередь")
        track = self.current
        fields = [("Длительность", format_duration(track['duration']), True), ("Запросил", track['requester'].mention, True)]
        if track['uploader']: fields.append(("Автор", f"[{track['uploader']}]({track['uploader_url']})" if track['uploader_url'] else track['uploader'], True))
        if self.queue: fields.append((f"Следующий трек (очередь: {len(self.queue)})", f"**{self.queue[0]['title']}**", False))
        return create_embed("🎵 Сейчас играет", f"**[{track['title']}]({track['url']})**", COLORS['DEFAULT'], thumbnail=track['thumbnail'], fields=fields)

    async def skip_track(self, ctx):
        """Пропускает текущий трек"""
        voice_client = ctx.guild.voice_client
        if not voice_client or not voice_client.is_playing(): await self.send_embed(ctx, "❌ Ошибка", "Ничего не воспроизводится", COLORS['ERROR']); return False
        is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
        is_requester = self.current and self.current['requester'].id == ctx.author.id
        if is_dj or is_requester:
            await self.send_embed(ctx, "⏭️ Трек пропущен", f"Трек пропущен по запросу {ctx.author.mention}", COLORS['SUCCESS']); voice_client.stop(); return True
        channel_members = len([m for m in voice_client.channel.members if not m.bot])
        required_votes = math.ceil(channel_members / 2)
        if ctx.author.id in self.skip_votes:
            await self.send_embed(ctx, "⏭️ Голосование", f"Вы уже голосовали!\nГолосов: {len(self.skip_votes)}/{required_votes}", COLORS['DEFAULT']); return False
        self.skip_votes.add(ctx.author.id)
        if len(self.skip_votes) >= required_votes:
            await self.send_embed(ctx, "⏭️ Трек пропущен", f"Трек пропущен по голосованию ({len(self.skip_votes)}/{required_votes})", COLORS['SUCCESS']); voice_client.stop(); return True
        else:
            await self.send_embed(ctx, "⏭️ Голосование", f"{ctx.author.mention} проголосовал за пропуск\nГолосов: {len(self.skip_votes)}/{required_votes}", COLORS['DEFAULT']); return False

    async def stop_playback(self, ctx):
        """Останавливает воспроизведение и очищает очередь"""
        voice_client = ctx.guild.voice_client
        if not voice_client: await self.send_embed(ctx, "❌ Ошибка", "Бот не подключен к голосовому каналу", COLORS['ERROR']); return False
        self.queue.clear(); self.is_paused = False
        if voice_client.is_playing() or voice_client.is_paused(): voice_client.stop()
        await voice_client.disconnect()
        if self.current and self.current.get('file') and os.path.exists(self.current['file']):
             try: os.remove(self.current['file']); logger.info(f"Удален файл текущего трека при остановке: {self.current['file']}")
             except Exception as e: logger.error(f"Не удалось удалить файл {self.current['file']} при остановке: {e}")
        if self.now_playing_message:
            try: await self.now_playing_message.delete()
            except: pass
        self.now_playing_message = None; self.current = None
        await self.send_embed(ctx, "⏹️ Остановлено", "Воспроизведение остановлено, очередь очищена", COLORS['SUCCESS']); return True

    async def pause_resume(self, ctx, pause=True):
        """Ставит на паузу или возобновляет воспроизведение"""
        voice_client = ctx.guild.voice_client
        if not voice_client: await self.send_embed(ctx, "❌ Ошибка", "Бот не подключен", COLORS['ERROR']); return False
        if pause and (not voice_client.is_playing() or voice_client.is_paused()): await self.send_embed(ctx, "❌ Ошибка", "Нет активного воспроизведения", COLORS['ERROR']); return False
        if not pause and not voice_client.is_paused(): await self.send_embed(ctx, "❌ Ошибка", "Воспроизведение не на паузе", COLORS['ERROR']); return False
        if pause: voice_client.pause(); self.is_paused = True; await self.send_embed(ctx, "⏸️ Пауза", "Воспроизведение приостановлено", COLORS['DEFAULT'])
        else: voice_client.resume(); self.is_paused = False; await self.send_embed(ctx, "▶️ Продолжение", "Воспроизведение возобновлено", COLORS['SUCCESS'])
        return True

    async def show_queue(self, ctx, items_per_page=10):
        """Показывает очередь воспроизведения"""
        if not self.queue and not self.current: await self.send_embed(ctx, "Очередь пуста", "Добавьте треки", COLORS['ERROR']); return
        description = []
        if self.current: desc = f"**🎵 Сейчас играет:**\n[{self.current['title']}]({self.current['url']}) | {format_duration(self.current['duration'])} | {self.current['requester'].mention}\n"; description.append(desc)
        if self.queue:
            description.append("**⏱️ В очереди:**")
            for i, track in enumerate(list(self.queue)[:items_per_page], 1): desc = f"{i}. [{track['title']}]({track['url']}) | {format_duration(track['duration'])} | {track['requester'].mention}"; description.append(desc)
            if len(self.queue) > items_per_page: description.append(f"\n*...и еще {len(self.queue) - items_per_page} трек(ов)*")
        await self.send_embed(ctx, "🎵 Очередь воспроизведения", "\n".join(description), footer=f"Всего треков: {len(self.queue) + (1 if self.current else 0)}")

    async def remove_from_queue(self, ctx, position):
        """Удаляет трек из очереди по указанной позиции."""
        if not self.queue: await self.send_embed(ctx, "❌ Ошибка", "Очередь пуста", COLORS['ERROR']); return False
        if not (1 <= position <= len(self.queue)): await self.send_embed(ctx, "❌ Ошибка", f"Позиция от 1 до {len(self.queue)}", COLORS['ERROR']); return False
        track = list(self.queue)[position - 1]
        is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
        is_requester = track['requester'].id == ctx.author.id
        if not (is_dj or is_requester): await self.send_embed(ctx, "❌ Ошибка", "Удалить может только DJ или запросивший", COLORS['ERROR']); return False
        del self.queue[position - 1]
        await self.send_embed(ctx, "🗑️ Трек удален", f"Трек **{track['title']}** удален", COLORS['SUCCESS']); return True

    async def search_tracks(self, ctx, query, max_results=5):
        """Ищет треки и позволяет пользователю выбрать из результатов"""
        loading_message = await self.send_embed(ctx, "🔍 Поиск", f"Ищу `{query}`...")
        try:
            search_opts = YDL_OPTS.copy(); search_opts['default_search'] = f'ytsearch{max_results}'; search_opts['extract_flat'] = True; search_opts['quiet'] = True
            ytdl = yt_dlp.YoutubeDL(search_opts)
            info = await self.loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch{max_results}:{query}", download=False))
            if not info or not info.get('entries'): await loading_message.edit(embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` ничего не найдено", COLORS['ERROR'])); return
            valid_entries = [entry for entry in info['entries'] if entry is not None]
            if not valid_entries: await loading_message.edit(embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` нет доступных результатов", COLORS['ERROR'])); return
            description = "Выберите трек, отправив его номер (или 'отмена'):"; fields = []
            for i, entry in enumerate(valid_entries, 1): fields.append((f"{i}. {entry.get('title', 'Неизвестно')}", f"Автор: {entry.get('uploader', 'Неизвестно')} | Длительность: {format_duration(entry.get('duration', 0))}", False))
            await loading_message.edit(embed=create_embed(f"🔍 Результаты поиска '{query}'", description, fields=fields))
            try:
                response = await self.bot.wait_for('message', check=lambda m: (m.author == ctx.author and m.channel == ctx.channel and (m.content.lower() in ['отмена', 'cancel'] or (m.content.isdigit() and 1 <= int(m.content) <= len(valid_entries)))), timeout=30)
                if response.content.lower() in ['отмена', 'cancel']: await self.send_embed(ctx, "🚫 Отменено", "Поиск отменен", COLORS['DEFAULT']); return
                choice = int(response.content) - 1; selected = valid_entries[choice]
                url = selected.get('url', selected.get('webpage_url'))
                if not url: await self.send_embed(ctx, "❌ Ошибка", "Не удалось получить URL", COLORS['ERROR']); return
                await self.add_track(ctx, url)
            except asyncio.TimeoutError: await self.send_embed(ctx, "⏱️ Время истекло", "Вы не выбрали трек", COLORS['ERROR'])
        except Exception as e: logger.error(f"Ошибка при поиске треков: {e}", exc_info=True); await loading_message.edit(embed=create_embed("❌ Ошибка", f"Ошибка при поиске: {str(e)[:900]}", COLORS['ERROR']))

async def ensure_voice(ctx):
    """Проверяет и обеспечивает голосовое подключение"""
    if not ctx.author.voice: await ctx.send(embed=create_embed("❌ Ошибка", "Вы должны быть в голосовом канале", COLORS['ERROR'])); return False
    voice_client = ctx.guild.voice_client
    if not voice_client: await ctx.author.voice.channel.connect()
    elif voice_client.channel != ctx.author.voice.channel: await voice_client.move_to(ctx.author.voice.channel)
    return True

async def handle_play(ctx, query):
    """Обрабатывает команду воспроизведения: проверяет канал, добавляет трек/ищет."""
    if not query: await ctx.send(embed=create_embed("❌ Ошибка", "Укажите запрос или ссылку", COLORS['ERROR'])); return
    if not await ensure_voice(ctx): return
    player = getattr(ctx.cog, 'player', None)
    if not player: await ctx.send("Ошибка: Экземпляр плеера не найден."); return
    if query.startswith(('http://', 'https://')): await player.add_track(ctx, query)
    else: await player.search_tracks(ctx, query)

async def handle_skip(ctx): player = getattr(ctx.cog, 'player', None); await (player.skip_track(ctx) if player else ctx.send("Ошибка: Плеер не найден."))
async def handle_stop(ctx): player = getattr(ctx.cog, 'player', None); await (player.stop_playback(ctx) if player else ctx.send("Ошибка: Плеер не найден."))
async def handle_pause(ctx): player = getattr(ctx.cog, 'player', None); await (player.pause_resume(ctx, pause=True) if player else ctx.send("Ошибка: Плеер не найден."))
async def handle_resume(ctx): player = getattr(ctx.cog, 'player', None); await (player.pause_resume(ctx, pause=False) if player else ctx.send("Ошибка: Плеер не найден."))
async def handle_remove(ctx, position): player = getattr(ctx.cog, 'player', None); await (player.remove_from_queue(ctx, position) if player else ctx.send("Ошибка: Плеер не найден."))
async def handle_queue(ctx): player = getattr(ctx.cog, 'player', None); await (player.show_queue(ctx) if player else ctx.send("Ошибка: Плеер не найден."))

async def cleanup_player(player: 'MusicPlayer', guild_name: str):
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

async def auto_disconnect(player: 'MusicPlayer', guild: discord.Guild, voice_channel: discord.VoiceChannel):
    """Автоматически отключает бота, если он остался один в канале."""
    if not player: logger.warning(f"Попытка автоотключения для несуществующего плеера в {guild.name}"); return
    if player.text_channel:
        try: await player.text_channel.send(embed=create_embed("👋 Автоотключение", "Все ушли, бот отключается.", COLORS['DEFAULT']))
        except Exception as e: logger.error(f"Ошибка при отправке сообщения об автоотключении: {e}")
    try:
        if guild.voice_client: await guild.voice_client.disconnect()
    except Exception as e: logger.error(f"Ошибка при отключении от голосового канала: {e}")
    await cleanup_player(player, guild.name)
    logger.info(f"Бот автоматически отключен от канала {voice_channel.name}")
