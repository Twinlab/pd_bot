import discord
import asyncio
import logging
import os
import math
import yt_dlp
import json
# import random # Больше не нужен
from collections import deque
import glob
from typing import Dict, List, Optional, Set, Any, Union, Callable
import subprocess

# Импортируем типы для аннотаций, чтобы избежать циклического импорта во время выполнения
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from discord.ext import commands
    # Убираем импорт MusicView, т.к. кнопки удалены
    # from cogs.music import MusicView

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
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '128',
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

# --- Класс музыкального плеера ---
class MusicPlayer:
    """
    Управляет состоянием воспроизведения музыки для одного сервера (гильдии).
    Включает очередь, управление воспроизведением и т.д.
    """
    def __init__(self, bot: commands.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.queue = deque()
        self.current: Optional[Dict] = None
        # self.volume = 0.5 # Громкость удалена
        self.text_channel: Optional[discord.TextChannel] = None
        self.now_playing_message: Optional[discord.Message] = None
        self.skip_votes: Set[int] = set()
        self.loop = asyncio.get_event_loop()
        self.is_playing_next = False
        self.is_paused = False
        # Атрибуты loop_mode и is_shuffled удалены

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        guild = self.bot.get_guild(self.guild_id)
        return guild.voice_client if guild else None

    async def _ensure_voice(self, ctx_or_channel: Union['commands.Context', discord.VoiceChannel]) -> bool:
        """Подключается к голосовому каналу."""
        target_channel: Optional[discord.VoiceChannel] = None
        author_to_check: Optional[discord.Member] = None
        response_target: Optional[Union['commands.Context', discord.Interaction]] = None

        if hasattr(ctx_or_channel, 'interaction') and ctx_or_channel.interaction:
             response_target = ctx_or_channel.interaction
             if not response_target.user.voice or not response_target.user.voice.channel:
                 await self.respond(response_target, "❌ Ошибка", "Вы должны быть в голосовом канале.", COLORS['ERROR'], ephemeral=True)
                 return False
             target_channel = response_target.user.voice.channel
             author_to_check = response_target.user
        elif isinstance(ctx_or_channel, commands.Context):
             response_target = ctx_or_channel
             if not ctx_or_channel.author.voice or not ctx_or_channel.author.voice.channel:
                 await self.respond(response_target, "❌ Ошибка", "Вы должны быть в голосовом канале.", COLORS['ERROR'], ephemeral=True)
                 return False
             target_channel = ctx_or_channel.author.voice.channel
             author_to_check = ctx_or_channel.author
        elif isinstance(ctx_or_channel, discord.VoiceChannel):
             target_channel = ctx_or_channel
        else:
             logger.error(f"Неверный тип для _ensure_voice: {type(ctx_or_channel)}")
             return False

        vc = self.voice_client
        if not vc:
            try:
                logger.info(f"Подключение к каналу: {target_channel.name}")
                await target_channel.connect()
                return True
            except Exception as e:
                logger.error(f"Ошибка при подключении к каналу {target_channel.name}: {e}", exc_info=True)
                if response_target:
                    await self.respond(response_target, "❌ Ошибка", f"Не удалось подключиться: {e}", COLORS['ERROR'], ephemeral=True)
                return False # Исправлено: разнесено на несколько строк
        elif vc.channel.id != target_channel.id:
            if author_to_check and not target_channel.permissions_for(author_to_check).connect:
                 if response_target:
                     await self.respond(response_target, "❌ Ошибка", "Нет прав для подключения к этому каналу.", COLORS['ERROR'], ephemeral=True)
                 return False
            try:
                logger.info(f"Перемещение в канал: {target_channel.name}")
                await vc.move_to(target_channel)
                return True
            except Exception as e:
                logger.error(f"Ошибка при перемещении в канал {target_channel.name}: {e}", exc_info=True)
                if response_target:
                    await self.respond(response_target, "❌ Ошибка", f"Не удалось переместиться: {e}", COLORS['ERROR'], ephemeral=True)
                return False # Исправлено: разнесено на несколько строк
        return True

    async def respond(self, target: Union['commands.Context', discord.Interaction], title: str, description: str, color: discord.Color = COLORS['DEFAULT'], ephemeral: bool = False, view: Optional[discord.ui.View] = None, **kwargs):
        """Отправляет ответ через контекст или взаимодействие."""
        embed = create_embed(title, description, color, **kwargs)
        try:
            if isinstance(target, discord.Interaction):
                if not target.response.is_done(): await target.response.send_message(embed=embed, ephemeral=ephemeral, view=view)
                else: await target.followup.send(embed=embed, ephemeral=ephemeral, view=view)
            elif isinstance(target, commands.Context): await target.send(embed=embed, view=view)
            if isinstance(target, discord.Interaction): self.last_interaction = target
            elif isinstance(target, commands.Context) and target.interaction: self.last_interaction = target.interaction
        except Exception as e:
            logger.error(f"Ошибка при отправке ответа: {e}")
            try: user_to_dm = target.user if isinstance(target, discord.Interaction) else target.author; await user_to_dm.send(embed=embed); logger.warning("Ответ отправлен в ЛС из-за ошибки.")
            except Exception: logger.error("Не удалось отправить ответ даже в ЛС.")

    async def send_message(self, ctx: Optional['commands.Context'], title: str, description: str, color: discord.Color = COLORS['DEFAULT'], **kwargs):
        """Отправляет эмбед-сообщение в основной текстовый канал плеера."""
        if ctx and not self.text_channel: self.text_channel = ctx.channel
        channel_to_send = self.text_channel
        if channel_to_send:
            try: await channel_to_send.send(embed=create_embed(title, description, color, **kwargs))
            except Exception as e: logger.error(f"Не удалось отправить сообщение в {channel_to_send.id}: {e}")
        else: logger.error("Не удалось определить канал для отправки сообщения плеера.")

    async def add_track(self, ctx: Union['commands.Context', discord.Interaction], url_or_search: str):
        """Скачивает трек (или ищет) и добавляет в очередь."""
        if not await self._ensure_voice(ctx): return
        response_target = ctx.interaction if hasattr(ctx, 'interaction') else ctx
        await self.respond(response_target, "🔄 Загрузка", "Скачиваем трек...", ephemeral=True)
        try:
            track = await self._download_track(url_or_search, response_target.user)
            self.queue.append(track)
            file_size = os.path.getsize(track['file']) / (1024 * 1024) if os.path.exists(track['file']) else 0
            position = len(self.queue)
            is_playing = self.voice_client and self.voice_client.is_playing()
            embed = create_embed("✅ Трек добавлен", f"**[{track['title']}]({track['url']})**", COLORS['SUCCESS'], thumbnail=track['thumbnail'], fields=[("Файл", f"`{os.path.basename(track['file'])}` ({file_size:.2f} МБ)", True), ("Длительность", format_duration(track['duration']), True), ("Запросил", response_target.user.mention, True)], footer=f"Позиция в очереди: {position}" if position > 0 or is_playing else "Сейчас играет")
            await response_target.edit_original_response(embed=embed, view=None)
            self.text_channel = response_target.channel
            if not self.voice_client.is_playing() and not self.is_paused: await self.play_next()
        except Exception as e: logger.error(f"Ошибка при добавлении трека: {e}", exc_info=True); await response_target.edit_original_response(embed=create_embed("❌ Ошибка", f"Не удалось добавить трек: {e}", COLORS['ERROR']), view=None)

    async def _download_track(self, url, requester):
        """Скачивает трек и возвращает информацию о нем."""
        ytdl = yt_dlp.YoutubeDL(YDL_OPTS)
        info = await self.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=True))
        if 'entries' in info: info = info['entries'][0]
        filename = ytdl.prepare_filename(info); base_filename = os.path.splitext(filename)[0]
        audio_file = None
        for ext in ['.opus', '.mp3', '.m4a', '.webm']:
            if os.path.exists(f"{base_filename}{ext}"): audio_file = f"{base_filename}{ext}"; logger.info(f"Найден скачанный файл: {audio_file}"); break
        if not audio_file:
            matching_files = glob.glob(f"{base_filename}.*")
            if matching_files: audio_file = matching_files[0]; logger.warning(f"Файл с ожидаемым расширением не найден, используется: {audio_file}")
            else: raise FileNotFoundError(f"Скачанный аудиофайл не найден: {base_filename}.*")
        if os.path.getsize(audio_file) == 0: raise ValueError(f"Скачанный файл имеет нулевой размер: {audio_file}")
        return {'file': audio_file, 'title': info.get('title', 'Unknown title'), 'url': info.get('webpage_url', info.get('url')), 'duration': info.get('duration', 0), 'thumbnail': info.get('thumbnail'), 'requester': requester, 'uploader': info.get('uploader', 'Unknown uploader'), 'uploader_url': info.get('uploader_url'), 'id': info.get('id', '')}

    async def play_next(self):
        """Воспроизводит следующий трек из очереди."""
        if self.is_playing_next: return
        self.is_playing_next = True
        vc = self.voice_client
        if not vc: self.is_playing_next = False; return

        try:
            next_track = None
            if self.queue:
                next_track = self.queue.popleft()
                logger.info(f"Следующий трек из очереди: {next_track['title']}")
            else:
                logger.info("Очередь пуста, воспроизведение завершено.")
                if self.now_playing_message:
                    try: await self.now_playing_message.edit(view=None)
                    except: pass
                self.now_playing_message = None; self.current = None
                if self.text_channel: await self.text_channel.send(embed=create_embed("🎵 Очередь завершена", "Очередь пуста.", COLORS['DEFAULT']))
                self.is_playing_next = False; return

            self.current = next_track
            file_path = self.current['file']
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0: raise FileNotFoundError(f"Файл трека недоступен: {file_path}")

            logger.info(f"Создание FFmpegPCMAudio для: {file_path}")
            try:
                ffmpeg_options = {'options': '-vn -loglevel warning'}
                audio = discord.FFmpegPCMAudio(file_path, **ffmpeg_options)
                # Используем volume=1.0, т.к. команда volume удалена
                source = discord.PCMVolumeTransformer(audio, volume=1.0)
                logger.info(f"Аудио источник создан.")
            except Exception as audio_error:
                logger.error(f"Ошибка FFmpegPCMAudio: {audio_error}", exc_info=True)
                if self.text_channel: await self.text_channel.send(embed=create_embed("❌ Ошибка FFmpeg", f"Не удалось обработать аудиофайл.\nОшибка: `{audio_error}`", COLORS['ERROR']))
                raise

            # --- Синхронный callback ---
            def after_playback(error):
                finished_track_path = track.get('file')
                original_track_info = track
                if error:
                    logger.error(f"Ошибка воспроизведения '{original_track_info.get('title', 'N/A')}' (в callback): {error}")
                    return_code = None
                    if isinstance(source, discord.PCMVolumeTransformer) and isinstance(source.original, discord.FFmpegPCMAudio) and hasattr(source.original, '_process') and source.original._process:
                         return_code = source.original._process.returncode
                         logger.error(f"Процесс FFmpeg завершился с кодом: {return_code}")
                else:
                    logger.debug(f"Трек '{original_track_info.get('title', 'N/A')}' завершен, планируем следующий.")
                    self.loop.call_soon_threadsafe(asyncio.create_task, self.play_next())

                # Удаляем файл
                if finished_track_path and os.path.exists(finished_track_path):
                    try: os.remove(finished_track_path); logger.info(f"Удален файл: {finished_track_path}")
                    except Exception as e: logger.error(f"Не удалось удалить файл {finished_track_path}: {e}")

            logger.info(f"Вызов voice_client.play() для трека: {self.current['title']}")
            vc.play(source, after=after_playback)
            logger.info(f"Воспроизведение трека запущено.")

            # Отправляем или редактируем сообщение "Сейчас играет"
            embed = self._create_now_playing_embed()
            from cogs.music import MusicView # Импортируем здесь
            view = MusicView(self) # Создаем View с базовыми кнопками

            if self.text_channel:
                if self.now_playing_message:
                    try:
                        await self.now_playing_message.edit(embed=embed, view=view)
                    except discord.NotFound:
                        self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
                    except Exception as e:
                        logger.error(f"Не удалось отредактировать 'Сейчас играет': {e}")
                        try:
                            self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
                        except Exception as e2:
                            logger.error(f"Не удалось отправить новое 'Сейчас играет': {e2}") # Исправлено: разнесено
                else:
                     try:
                         self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
                     except Exception as e:
                         logger.error(f"Не удалось отправить 'Сейчас играет': {e}")

        except Exception as e:
            logger.error(f"Ошибка в play_next: {e}", exc_info=True)
            if self.text_channel: await self.text_channel.send(embed=create_embed("❌ Ошибка", f"Ошибка воспроизведения: {e}", COLORS['ERROR']))
            await asyncio.sleep(1)
            asyncio.create_task(self.play_next())
        finally:
            self.is_playing_next = False

    def _create_now_playing_embed(self):
        """Создает эмбед для текущего трека"""
        if not self.current: return create_embed("Ничего не играет", "Добавьте треки в очередь")
        track = self.current
        fields = [("Длительность", format_duration(track['duration']), True), ("Запросил", track['requester'].mention, True)]
        if track['uploader']: fields.append(("Автор", f"[{track['uploader']}]({track['uploader_url']})" if track['uploader_url'] else track['uploader'], True))
        if self.queue: fields.append((f"Следующий трек ({len(self.queue)})", f"**{self.queue[0]['title']}**", False))
        # Убрали футер с loop/shuffle/volume
        return create_embed("🎵 Сейчас играет", f"**[{track['title']}]({track['url']})**", COLORS['DEFAULT'], thumbnail=track['thumbnail'], fields=fields)

    async def skip(self, target: Union['commands.Context', discord.Interaction]):
        """Пропускает текущий трек (с голосованием или без)."""
        vc = self.voice_client; user = target.user if isinstance(target, discord.Interaction) else target.author
        if not vc or not vc.is_playing(): await self.respond(target, "❌ Ошибка", "Ничего не воспроизводится.", COLORS['ERROR'], ephemeral=True); return
        is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in user.roles)
        is_requester = self.current and self.current['requester'].id == user.id
        if is_dj or is_requester: await self.respond(target, "⏭️ Трек пропущен", f"Трек пропущен по запросу {user.mention}.", COLORS['SUCCESS'], ephemeral=False); vc.stop(); return
        channel_members = len([m for m in vc.channel.members if not m.bot]); required_votes = math.ceil(channel_members / 2)
        if user.id in self.skip_votes: await self.respond(target, "⏭️ Голосование", f"Вы уже голосовали!\nГолосов: {len(self.skip_votes)}/{required_votes}", COLORS['DEFAULT'], ephemeral=True); return
        self.skip_votes.add(user.id)
        if len(self.skip_votes) >= required_votes: await self.respond(target, "⏭️ Трек пропущен", f"Трек пропущен по голосованию ({len(self.skip_votes)}/{required_votes}).", COLORS['SUCCESS'], ephemeral=False); vc.stop()
        else: await self.respond(target, "⏭️ Голосование", f"{user.mention} проголосовал за пропуск.\nГолосов: {len(self.skip_votes)}/{required_votes}", COLORS['DEFAULT'], ephemeral=False)

    async def stop(self, target: Optional[Union['commands.Context', discord.Interaction]] = None):
        """Останавливает воспроизведение, очищает очередь и отключается."""
        vc = self.voice_client
        if not vc:
            if target: await self.respond(target, "❌ Ошибка", "Бот не в голосовом канале.", COLORS['ERROR'], ephemeral=True)
            return
        logger.info("Остановка воспроизведения и очистка.")
        self.queue.clear(); self.is_paused = False
        if vc.is_playing() or vc.is_paused(): vc.stop()
        if self.now_playing_message:
            try: await self.now_playing_message.edit(view=None)
            except: pass
        self.now_playing_message = None; self.current = None; self.skip_votes.clear()
        await vc.disconnect()
        logger.info(f"Бот отключен от канала {vc.channel.name}")
        if target: await self.respond(target, "⏹️ Остановлено", "Воспроизведение остановлено.", COLORS['SUCCESS'], ephemeral=True)

    async def pause(self, target: Union['commands.Context', discord.Interaction]):
        """Ставит воспроизведение на паузу."""
        vc = self.voice_client
        if not vc or not vc.is_playing(): await self.respond(target, "❌ Ошибка", "Нет активного воспроизведения.", COLORS['ERROR'], ephemeral=True); return
        if vc.is_paused(): await self.respond(target, "ℹ️ Инфо", "Уже на паузе.", COLORS['DEFAULT'], ephemeral=True); return
        vc.pause(); self.is_paused = True
        await self.respond(target, "⏸️ Пауза", "Воспроизведение приостановлено.", COLORS['DEFAULT'], ephemeral=True)
        if self.now_playing_message and self.now_playing_message.view:
             view = self.now_playing_message.view
             if hasattr(view, 'update_buttons'): view.update_buttons()
             try: await self.now_playing_message.edit(view=view)
             except: pass

    async def resume(self, target: Union['commands.Context', discord.Interaction]):
        """Возобновляет воспроизведение."""
        vc = self.voice_client
        if not vc or not vc.is_paused(): await self.respond(target, "❌ Ошибка", "Воспроизведение не на паузе.", COLORS['ERROR'], ephemeral=True); return
        vc.resume(); self.is_paused = False
        await self.respond(target, "▶️ Продолжение", "Воспроизведение возобновлено.", COLORS['SUCCESS'], ephemeral=True)
        if self.now_playing_message and self.now_playing_message.view:
             view = self.now_playing_message.view
             if hasattr(view, 'update_buttons'): view.update_buttons()
             try: await self.now_playing_message.edit(view=view)
             except: pass

    async def remove(self, ctx: commands.Context, position: int):
        """Удаляет трек из очереди по позиции."""
        if not self.queue: await self.respond(ctx, "❌ Ошибка", "Очередь пуста.", COLORS['ERROR'], ephemeral=True); return
        if not (1 <= position <= len(self.queue)): await self.respond(ctx, "❌ Ошибка", f"Позиция от 1 до {len(self.queue)}.", COLORS['ERROR'], ephemeral=True); return
        try:
            track_to_remove = list(self.queue)[position - 1]
            is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
            is_requester = track_to_remove['requester'].id == ctx.author.id
            if not (is_dj or is_requester): await self.respond(ctx, "❌ Ошибка", "Удалить может только DJ или запросивший.", COLORS['ERROR'], ephemeral=True); return
            del self.queue[position - 1]
            await self.respond(ctx, "🗑️ Трек удален", f"Трек **{track_to_remove['title']}** удален.", COLORS['SUCCESS'], ephemeral=True)
        except IndexError: await self.respond(ctx, "❌ Ошибка", "Неверная позиция.", COLORS['ERROR'], ephemeral=True)
        except Exception as e: logger.error(f"Ошибка при удалении трека: {e}", exc_info=True); await self.respond(ctx, "❌ Ошибка", f"Не удалось удалить: {e}", COLORS['ERROR'], ephemeral=True)

    async def show_queue(self, ctx: commands.Context, items_per_page=10):
        """Показывает очередь воспроизведения."""
        if not self.queue and not self.current: await self.respond(ctx, "Очередь пуста", "Добавьте треки", COLORS['ERROR'], ephemeral=True); return
        description = []
        if self.current: desc = f"**🎵 Сейчас играет:**\n[{self.current['title']}]({self.current['url']}) | {format_duration(self.current['duration'])} | {self.current['requester'].mention}\n"; description.append(desc)
        if self.queue:
            description.append("**⏱️ В очереди:**")
            for i, track in enumerate(list(self.queue)[:items_per_page], 1): desc = f"{i}. [{track['title']}]({track['url']}) | {format_duration(track['duration'])} | {track['requester'].mention}"; description.append(desc)
            if len(self.queue) > items_per_page: description.append(f"\n*...и еще {len(self.queue) - items_per_page} трек(ов)*")
        await self.respond(ctx, "🎵 Очередь воспроизведения", "\n".join(description), footer=f"Всего треков: {len(self.queue) + (1 if self.current else 0)}", ephemeral=False)

    # Методы set_volume, toggle_loop, shuffle_queue удалены

    async def search_tracks(self, ctx: Union['commands.Context', discord.Interaction], query, max_results=5):
        """Ищет треки и позволяет пользователю выбрать из результатов"""
        response_target = ctx.interaction if hasattr(ctx, 'interaction') else ctx
        await self.respond(response_target, "🔍 Поиск", f"Ищу `{query}`...", ephemeral=True)
        try:
            search_opts = YDL_OPTS.copy(); search_opts['default_search'] = f'ytsearch{max_results}'; search_opts['extract_flat'] = True; search_opts['quiet'] = True
            ytdl = yt_dlp.YoutubeDL(search_opts)
            info = await self.loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch{max_results}:{query}", download=False))
            if not info or not info.get('entries'): await response_target.edit_original_response(embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` ничего не найдено", COLORS['ERROR']), view=None); return
            valid_entries = [entry for entry in info['entries'] if entry is not None]
            if not valid_entries: await response_target.edit_original_response(embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` нет доступных результатов", COLORS['ERROR']), view=None); return
            description = "Выберите трек, отправив его номер (или 'отмена'):"; fields = []
            for i, entry in enumerate(valid_entries, 1): fields.append((f"{i}. {entry.get('title', 'Неизвестно')}", f"Автор: {entry.get('uploader', 'Неизвестно')} | Длительность: {format_duration(entry.get('duration', 0))}", False))
            await response_target.edit_original_response(embed=create_embed(f"🔍 Результаты поиска '{query}'", description, fields=fields), view=None)
            try:
                response = await self.bot.wait_for('message', check=lambda m: (m.author == response_target.user and m.channel == response_target.channel and (m.content.lower() in ['отмена', 'cancel'] or (m.content.isdigit() and 1 <= int(m.content) <= len(valid_entries)))), timeout=30)
                if response.content.lower() in ['отмена', 'cancel']: await self.respond(response_target, "🚫 Отменено", "Поиск отменен", COLORS['DEFAULT'], ephemeral=True); return
                choice = int(response.content) - 1; selected = valid_entries[choice]
                url = selected.get('url', selected.get('webpage_url'))
                if not url: await self.respond(response_target, "❌ Ошибка", "Не удалось получить URL", COLORS['ERROR'], ephemeral=True); return
                await self.add_track(ctx, url)
            except asyncio.TimeoutError: await self.respond(response_target, "⏱️ Время истекло", "Вы не выбрали трек", COLORS['ERROR'], ephemeral=True)
        except Exception as e: logger.error(f"Ошибка при поиске треков: {e}", exc_info=True); await response_target.edit_original_response(embed=create_embed("❌ Ошибка", f"Ошибка при поиске: {str(e)[:900]}", COLORS['ERROR']), view=None)

# Старые handle_ функции удалены
