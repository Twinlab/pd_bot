import asyncio
import os
from collections import deque
from typing import Optional, Dict, Any, Deque
import discord

from .config import logger, FFMPEG_OPTIONS, COLORS
from .embeds import create_embed, format_duration
from .yt_integration import download_track

class Track:
    """Представляет трек в очереди."""
    def __init__(self, info: Dict[str, Any], requester: discord.Member):
        self.url: str = info.get('webpage_url', info.get('original_url', ''))
        self.title: str = info.get('title', 'Неизвестное название')
        self.duration: Optional[int] = info.get('duration')
        self.thumbnail: Optional[str] = info.get('thumbnail')
        self.uploader: Optional[str] = info.get('uploader')
        self.uploader_url: Optional[str] = info.get('uploader_url')
        self.requester: discord.Member = requester
        self.id: str = info.get('id', '')
        self.extractor: str = info.get('extractor_key', 'youtube').lower()
        self.filepath: Optional[str] = None

    def __str__(self) -> str:
        return f"**{self.title}** ({format_duration(self.duration)})"

    def to_embed_field(self, index: Optional[int] = None):
        name = f"`{index}.` {self.title}" if index is not None else self.title
        value = f"`{format_duration(self.duration)}` | Запросил: {self.requester.mention}"
        if self.uploader:
            value += f"\nАвтор: [{self.uploader}]({self.uploader_url})" if self.uploader_url else f"\nАвтор: {self.uploader}"
        return (name, value, False)

class MusicPlayer:
    """Управляет состоянием и воспроизведением музыки (для одного сервера)."""
    def __init__(self, bot):
        self.bot = bot
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.TextChannel] = None
        self.queue: Deque[Track] = deque()
        self.current_track: Optional[Track] = None
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.loop = asyncio.get_event_loop()
        self.now_playing_message: Optional[discord.Message] = None
        self.player_view = None
        self._play_next_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    async def connect(self, channel: discord.VoiceChannel) -> bool:
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel == channel:
                return True
            try:
                logger.info(f"Перемещение в голосовой канал: {channel.name} ({channel.id})")
                await self.voice_client.move_to(channel)
                return True
            except asyncio.TimeoutError:
                logger.error(f"Таймаут при перемещении в голосовой канал: {channel.name}")
                return False
            except Exception as e:
                logger.error(f"Ошибка при перемещении в голосовой канал {channel.name}: {e}", exc_info=True)
                await self.disconnect()
        try:
            logger.info(f"Подключение к голосовому каналу: {channel.name} ({channel.id})")
            self.voice_client = await channel.connect(timeout=30.0, reconnect=True)
            logger.info(f"Успешно подключились к {channel.name}")
            return True
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при подключении к голосовому каналу: {channel.name}")
            self.voice_client = None
            return False
        except discord.ClientException as e:
            logger.error(f"ClientException при подключении к {channel.name}: {e}")
            if channel.guild.voice_client:
                self.voice_client = channel.guild.voice_client
                logger.warning(f"Найдено существующее голосовое подключение в {self.voice_client.channel.name}. Перемещаемся, если необходимо.")
                return await self.connect(channel)
            self.voice_client = None
            return False
        except Exception as e:
            logger.error(f"Ошибка при подключении к голосовому каналу {channel.name}: {e}", exc_info=True)
            self.voice_client = None
            return False

    async def disconnect(self, interaction: Optional[discord.Interaction] = None):
        logger.info("Отключение и очистка плеера...")
        if self._play_next_task:
            self._play_next_task.cancel()
            self._play_next_task = None
        if self.voice_client and self.voice_client.is_connected():
            logger.info(f"Остановка воспроизведения и отключение от {self.voice_client.channel.name}")
            self.voice_client.stop()
            await self.voice_client.disconnect(force=True)
            self.voice_client = None
        else:
            logger.info("Голосовой клиент не подключен или уже отключен.")
        await self.cleanup(clear_queue=True)
        if interaction and not interaction.response.is_done():
            await interaction.response.send_message("⏹️ Воспроизведение остановлено, бот отключен.", ephemeral=True)
        elif self.text_channel:
            try:
                await self.text_channel.send(embed=create_embed("👋 Автоотключение", "Бот отключен из-за неактивности или пустого канала.", COLORS['INFO']))
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение об автоотключении: {e}")
        logger.info("Плеер отключен и очищен.")

    async def queue_track(self, url: str, requester: discord.Member, interaction: Optional[discord.Interaction] = None):
        response_method = interaction.followup.send if interaction else (self.text_channel.send if self.text_channel else None)
        edit_method = interaction.edit_original_response if interaction else None
        loading_msg = None
        if edit_method:
            try:
                await edit_method(content="🔄 Скачивание трека...")
            except discord.NotFound:
                edit_method = None
                if response_method:
                    loading_msg = await response_method(embed=create_embed("🔄 Загрузка", "Скачиваем трек..."), wait=True if interaction else False)
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение о загрузке: {e}")
                edit_method = None
                if response_method:
                    loading_msg = await response_method(embed=create_embed("🔄 Загрузка", "Скачиваем трек..."), wait=True if interaction else False)
        elif response_method:
            loading_msg = await response_method(embed=create_embed("🔄 Загрузка", "Скачиваем трек..."), wait=True if interaction else False)
        update_msg_method = loading_msg.edit if loading_msg and not edit_method else edit_method
        try:
            logger.info(f"Скачивание трека: {url}")
            track_info = await download_track(url)
            if not track_info:
                raise ValueError("Не удалось получить информацию о треке.")
            track = Track(track_info, requester)
            track.filepath = track_info.get('filepath')
            if not track.filepath or not os.path.exists(track.filepath):
                raise FileNotFoundError(f"Скачанный файл не найден: {track.filepath}")
            if os.path.getsize(track.filepath) == 0:
                raise ValueError(f"Скачанный файл имеет нулевой размер: {track.filepath}")
            self.queue.append(track)
            logger.info(f"Трек добавлен в очередь: {track.title}")
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
                await update_msg_method(content=None, embed=embed, view=None)
            elif response_method:
                await response_method(embed=embed)
            if not self.is_playing and self.voice_client and self.voice_client.is_connected():
                self.start_playback_loop()
        except Exception as e:
            logger.error(f"Ошибка при добавлении трека {url}: {e}", exc_info=True)
            error_embed = create_embed("❌ Ошибка", f"Произошла ошибка при добавлении трека:\n`{e}`", COLORS['ERROR'])
            if update_msg_method:
                await update_msg_method(content=None, embed=error_embed, view=None)
            elif response_method:
                await response_method(embed=error_embed)

    def start_playback_loop(self):
        if self._play_next_task and not self._play_next_task.done():
            logger.debug("Цикл воспроизведения уже запущен.")
            return
        logger.info("Запуск цикла воспроизведения...")
        self._play_next_task = self.loop.create_task(self.play_next())

    async def play_next(self):
        try:
            if not self.voice_client or not self.voice_client.is_connected():
                logger.warning("play_next вызван, но голосовой клиент не подключен.")
                await self.cleanup()
                return
            if self.is_playing:
                logger.debug("play_next вызван во время воспроизведения. Игнорируем.")
                return
            if not self.queue:
                logger.info("Очередь пуста. Воспроизведение завершено.")
                await self.cleanup(clear_queue=False)
                return
            self.current_track = self.queue.popleft()
            logger.info(f"Воспроизведение следующего трека: {self.current_track.title}")
            if not self.current_track.filepath or not os.path.exists(self.current_track.filepath):
                logger.error(f"Путь к файлу отсутствует или файл не найден для трека: {self.current_track.title} ({self.current_track.filepath})")
                await self.send_error_message(f"Ошибка: Файл для трека '{self.current_track.title}' не найден.")
                self.current_track = None
                self.start_playback_loop()
                return
            try:
                if not os.path.exists(self.current_track.filepath):
                    raise FileNotFoundError(f"Файл не найден: {self.current_track.filepath}")
                file_size = os.path.getsize(self.current_track.filepath)
                if file_size == 0:
                    raise ValueError(f"Файл имеет нулевой размер: {self.current_track.filepath}")
                logger.info(f"Создание аудио источника для файла: {self.current_track.filepath} (размер: {file_size} байт)")
                source = discord.FFmpegPCMAudio(self.current_track.filepath, **FFMPEG_OPTIONS)
                logger.info(f"Аудио источник успешно создан для трека: {self.current_track.title}")
            except Exception as e:
                logger.error(f"Ошибка создания FFmpegPCMAudio для {self.current_track.filepath}: {e}", exc_info=True)
                await self.send_error_message(f"Ошибка при обработке трека '{self.current_track.title}'.")
                self.current_track = None
                self.start_playback_loop()
                return
            self.voice_client.play(source, after=lambda e: self.loop.create_task(self._after_playback(e)))
            self.is_playing = True
            self.is_paused = False
            logger.info(f"Воспроизведение начато для: {self.current_track.title}")
            await self._update_now_playing_message()
        except Exception as e:
            logger.error(f"Ошибка в цикле play_next: {e}", exc_info=True)
            await self.send_error_message("Произошла критическая ошибка в цикле воспроизведения.")
            await self.stop()

    async def _after_playback(self, error: Optional[Exception]):
        logger.debug(f"_after_playback вызван. Ошибка: {error}")
        finished_track = self.current_track
        self.is_playing = False
        self.current_track = None
        if error:
            logger.error(f"Ошибка воспроизведения: {error}", exc_info=error)
            await self.send_error_message(f"Ошибка во время воспроизведения трека '{finished_track.title if finished_track else ''}': `{error}`")
        if self.queue and self.voice_client and self.voice_client.is_connected():
            self.start_playback_loop()
        elif self.voice_client and self.voice_client.is_connected():
            logger.info("Очередь завершена, но клиент все еще подключен.")
            await self.cleanup(clear_queue=False)
        else:
            logger.info("Воспроизведение завершено и клиент отключен.")
            await self.cleanup(clear_queue=False)

    async def pause(self, interaction: Optional[discord.Interaction] = None):
        if self.voice_client and self.is_playing and not self.is_paused:
            logger.info("Приостановка воспроизведения.")
            self.voice_client.pause()
            self.is_paused = True
            if interaction:
                await interaction.response.send_message("⏸️ Воспроизведение приостановлено.", ephemeral=True)
            await self._update_now_playing_message()
        elif interaction:
            await interaction.response.send_message("Сейчас ничего не играет или уже на паузе.", ephemeral=True)

    async def resume(self, interaction: Optional[discord.Interaction] = None):
        if self.voice_client and self.is_paused:
            logger.info("Возобновление воспроизведения.")
            self.voice_client.resume()
            self.is_paused = False
            if interaction:
                await interaction.response.send_message("▶️ Воспроизведение возобновлено.", ephemeral=True)
            await self._update_now_playing_message()
        elif interaction:
            await interaction.response.send_message("Воспроизведение не на паузе.", ephemeral=True)

    async def skip(self, interaction: Optional[discord.Interaction] = None):
        if self.voice_client and self.is_playing:
            logger.info(f"Пропуск трека: {self.current_track.title if self.current_track else 'Неизвестно'}")
            skipped_title = self.current_track.title if self.current_track else "текущий трек"
            self.voice_client.stop()
            if interaction:
                await interaction.response.send_message(f"⏭️ Трек '{skipped_title}' пропущен.", ephemeral=True)
        elif interaction:
            await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)

    async def stop(self, interaction: Optional[discord.Interaction] = None):
        logger.info("Получена команда stop.")
        await self.disconnect(interaction)

    async def show_queue(self, interaction: discord.Interaction):
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
            description_lines.append("")
        if self.queue:
            description_lines.append("**⏱️ В очереди:**")
            queue_list = list(self.queue)
            total_duration = sum(t.duration for t in queue_list if t.duration) + (self.current_track.duration if self.current_track and self.current_track.duration else 0)
            for i, track in enumerate(queue_list[:15], 1):
                name, value, _ = track.to_embed_field(index=i)
                description_lines.append(f"{name}\n{value}")
            if len(queue_list) > 15:
                description_lines.append(f"\n*...и еще {len(queue_list) - 15} трек(ов)*")
            embed.set_footer(text=f"Всего треков: {len(queue_list) + (1 if self.current_track else 0)} | Общая длительность: {format_duration(total_duration)}")
        elif self.current_track:
            embed.set_footer(text=f"Всего треков: 1 | Общая длительность: {format_duration(self.current_track.duration)}")
        embed.description = "\n".join(description_lines)[:4096]
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _update_now_playing_message(self):
        if not self.text_channel:
            logger.warning("_update_now_playing_message вызван без text_channel.")
            return
        from .ui import PlayerControlView
        embed = self._create_now_playing_embed()
        view = self.player_view or PlayerControlView(self)
        view._update_buttons()
        if self.now_playing_message:
            try:
                await self.now_playing_message.edit(embed=embed, view=view)
                logger.debug("Обновлено сообщение 'Сейчас играет'.")
            except discord.NotFound:
                logger.warning("Сообщение 'Сейчас играет' не найдено, отправляем новое.")
                self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
            except Exception as e:
                logger.error(f"Не удалось отредактировать сообщение 'Сейчас играет': {e}", exc_info=True)
                try:
                    self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
                except Exception as send_e:
                    logger.error(f"Не удалось отправить новое сообщение 'Сейчас играет': {send_e}", exc_info=True)
                    self.now_playing_message = None
        else:
            try:
                self.now_playing_message = await self.text_channel.send(embed=embed, view=view)
                logger.info("Отправлено сообщение 'Сейчас играет'.")
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение 'Сейчас играет': {e}", exc_info=True)
                self.now_playing_message = None
        self.player_view = view

    def _create_now_playing_embed(self) -> discord.Embed:
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
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
        return embed

    async def send_error_message(self, message: str):
        if self.text_channel:
            try:
                await self.text_channel.send(embed=create_embed("❌ Ошибка", message, COLORS['ERROR']))
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение об ошибке в текстовый канал: {e}")
        else:
            logger.warning(f"Невозможно отправить сообщение об ошибке, text_channel не установлен. Ошибка: {message}")

    async def cleanup(self, clear_queue: bool = True):
        logger.debug(f"Вызвана очистка. clear_queue={clear_queue}")
        self.is_playing = False
        self.is_paused = False
        self.current_track = None
        if self.player_view:
            self.player_view.stop()
            if self.now_playing_message:
                try:
                    await self.now_playing_message.edit(view=None)
                except discord.NotFound:
                    pass
                except Exception as e:
                    logger.warning(f"Не удалось удалить view при очистке: {e}")
            self.player_view = None
        if self.now_playing_message:
            try:
                await self.now_playing_message.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение 'Сейчас играет' при очистке: {e}")
            self.now_playing_message = None
        if clear_queue:
            logger.debug(f"Очистка очереди (содержит {len(self.queue)} элементов).")
            self.queue.clear()
        logger.debug("Очистка завершена.")

    async def start_cleanup_task(self):
        if not hasattr(self, '_cleanup_task') or self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = self.loop.create_task(self._scheduled_cleanup())
            logger.info("Запущена задача по очистке старых файлов")

    async def _scheduled_cleanup(self):
        import time, glob
        try:
            while True:
                await asyncio.sleep(24 * 60 * 60)
                await self._cleanup_old_files()
        except asyncio.CancelledError:
            logger.info("Задача очистки файлов отменена")
        except Exception as e:
            logger.error(f"Ошибка в задаче очистки файлов: {e}", exc_info=True)

    async def _cleanup_old_files(self):
        import time, glob
        try:
            now = time.time()
            one_hour_ago = now - 3600
            count = 0
            for file_path in glob.glob("downloads/*"):
                try:
                    file_creation_time = os.path.getctime(file_path)
                    if file_creation_time < one_hour_ago:
                        os.remove(file_path)
                        count += 1
                        logger.debug(f"Удален старый файл: {file_path}")
                except OSError as e:
                    logger.error(f"Ошибка при удалении старого файла {file_path}: {e}")
            if count > 0:
                logger.info(f"Очистка завершена: удалено {count} старых файлов")
        except Exception as e:
            logger.error(f"Ошибка при очистке старых файлов: {e}", exc_info=True)
