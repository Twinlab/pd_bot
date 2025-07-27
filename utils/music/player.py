"""Модуль, содержащий классы Track и MusicPlayer для управления музыкальным плеером."""

import asyncio
import logging
import subprocess
from collections import deque
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

import discord

from .config import COLORS, PROXY_URL
from .embeds import create_embed, format_duration
from .yt_integration import get_stream_info

# Создаем логгер с иерархическим именем
logger = logging.getLogger("bot.utils.music.player")

if TYPE_CHECKING:
    from discord.ext import commands  # Для type hinting bot


class Track:
    """Представляет музыкальный трек в очереди воспроизведения."""

    def __init__(self, info: Dict[str, Any], requester: discord.Member) -> None:
        """Инициализирует объект трека.

        Args:
            info: Словарь с информацией о треке, полученный от yt-dlp.
            requester: Участник Discord, запросивший трек.
        """
        self.url: str = info.get("webpage_url", info.get("original_url", ""))
        self.title: str = info.get("title", "Неизвестное название")
        self.duration: Optional[int] = info.get("duration")  # в секундах
        self.thumbnail: Optional[str] = info.get("thumbnail")
        self.uploader: Optional[str] = info.get("uploader")
        self.uploader_url: Optional[str] = info.get("uploader_url")
        self.requester: discord.Member = requester
        self.id: str = info.get("id", "")  # ID видео/трека с сервиса
        self.extractor: str = info.get(
            "extractor_key", "youtube"
        ).lower()  # Ключ экстрактора (youtube, soundcloud и т.д.)
        self.stream_url: str = info.get("url", "")  # URL для потокового воспроизведения

    def __str__(self) -> str:
        """Возвращает строковое представление трека (название и длительность)."""
        return f"**{self.title}** ({format_duration(self.duration)})"

    def to_embed_field(self, index: Optional[int] = None) -> tuple[str, str, bool]:
        """Форматирует информацию о треке для использования в качестве поля в discord.Embed.

        Args:
            index: Опциональный номер трека в очереди.

        Returns:
            Кортеж (name, value, inline) для discord.Embed.add_field().
        """
        name = f"`{index}.` {self.title}" if index is not None else self.title
        value = f"`{format_duration(self.duration)}` | Запросил: {self.requester.mention}"
        if self.uploader:
            uploader_link = (
                f"[{self.uploader}]({self.uploader_url})" if self.uploader_url else self.uploader
            )
            value += f"\nАвтор: {uploader_link}"
        return (name, value, False)


class MusicPlayer:
    """Управляет состоянием и воспроизведением музыки для одного сервера (гильдии).

    Включает управление очередью, подключением к голосовому каналу,
    воспроизведением треков и взаимодействием с пользователем.
    """

    def __init__(self, bot: "commands.Bot") -> None:
        """Инициализирует музыкальный плеер.

        Args:
            bot: Экземпляр бота commands.Bot.
        """
        self.bot: "commands.Bot" = bot
        self.voice_client: discord.VoiceClient | None = None
        self.text_channel: discord.TextChannel | discord.Thread | None = None
        self.queue: deque[Track] = deque()
        self.current_track: Track | None = None
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.loop = asyncio.get_event_loop()
        self.now_playing_message: discord.Message | None = None
        self.player_view: discord.ui.View | None = None
        self._play_next_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self.yt_process: Optional[subprocess.Popen] = None
        self.ffmpeg_process: Optional[subprocess.Popen] = None

    async def connect(self, channel: discord.VoiceChannel) -> bool:
        """Подключает или перемещает бота в указанный голосовой канал.

        Args:
            channel: Голосовой канал для подключения.

        Returns:
            True в случае успеха, False в противном случае.
        """
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel == channel:
                logger.debug(f"Бот уже в целевом канале: {channel.name}")
                return True
            try:
                logger.info(f"Перемещение в голосовой канал: {channel.name} ({channel.id})")
                await self.voice_client.move_to(channel)
                return True
            except asyncio.TimeoutError:
                logger.error(f"Таймаут при перемещении в голосовой канал: {channel.name}")
                return False
            except Exception as e:
                logger.error(
                    f"Ошибка при перемещении в голосовой канал {channel.name}: {e}", exc_info=True
                )
                await self.disconnect()
        try:
            # Получаем настройки
            from config.settings import get_settings

            settings = get_settings()

            logger.info(f"Подключение к голосовому каналу: {channel.name} ({channel.id})")
            self.voice_client = await channel.connect(
                timeout=settings.music.voice.connection_timeout, reconnect=True
            )
            logger.info(f"Успешно подключились к {channel.name}")
            return True
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при подключении к голосовому каналу: {channel.name}")
            self.voice_client = None
            return False
        except discord.ClientException as e:
            logger.error(f"ClientException при подключении к {channel.name}: {e}")
            if channel.guild.voice_client:
                self.voice_client = cast(discord.VoiceClient, channel.guild.voice_client)
                if self.voice_client and self.voice_client.channel:
                    logger.warning(
                        (
                            f"Найдено существующее голосовое подключение в "
                            f"{self.voice_client.channel.name}. "
                            "Перемещаемся, если необходимо."
                        )
                    )
                return await self.connect(channel)
            self.voice_client = None
            return False
        except Exception as e:
            logger.error(
                f"Ошибка при подключении к голосовому каналу {channel.name}: {e}", exc_info=True
            )
            self.voice_client = None
            return False

    async def disconnect(self, interaction: discord.Interaction | None = None) -> None:
        """Отключает бота от голосового канала и очищает состояние плеера.

        Args:
            interaction: Опциональное взаимодействие, чтобы ответить пользователю.
        """
        logger.info("Отключение и очистка плеера...")
        if self._play_next_task:
            self._play_next_task.cancel()
            self._play_next_task = None  # Явно обнуляем после отмены
        if self.voice_client and self.voice_client.is_connected():
            logger.info(
                f"Остановка воспроизведения и отключение от {self.voice_client.channel.name}"
            )
            self.voice_client.stop()
            await self.voice_client.disconnect(force=True)
            self.voice_client = None
        else:
            logger.info("Голосовой клиент не подключен или уже отключен.")
        await self.cleanup(clear_queue=True)
        if interaction and not interaction.response.is_done():
            await interaction.response.send_message(
                "⏹️ Воспроизведение остановлено, бот отключен.", ephemeral=True
            )
        elif self.text_channel:
            try:
                await self.text_channel.send(
                    embed=create_embed(
                        "👋 Автоотключение",
                        "Бот отключен из-за неактивности или пустого канала.",
                        COLORS["INFO"],
                    )
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение об автоотключении: {e}")
        logger.info("Плеер отключен и очищен.")

    async def queue_track(
        self, url: str, requester: discord.Member, interaction: discord.Interaction | None = None
    ) -> None:
        """Получает информацию о треке, добавляет в очередь и запускает воспроизведение.

        Если очередь была пуста, начинает воспроизведение.

        Args:
            url: URL-адрес трека.
            requester: Участник, запросивший трек.
            interaction: Опциональное взаимодействие для отправки сообщений о статусе.
        """
        response_method = (
            interaction.followup.send
            if interaction and interaction.response.is_done()
            else (
                interaction.response.send_message
                if interaction and not interaction.response.is_done()
                else None
            )
        )
        if not response_method and self.text_channel:
            response_method = self.text_channel.send  # type: ignore

        edit_method = interaction.edit_original_response if interaction else None
        loading_msg: Any = None

        if edit_method:
            try:
                await edit_method(content="🔄 Получение информации о треке...")
            except discord.NotFound:
                edit_method = None
                if response_method:
                    loading_msg = await response_method(
                        embed=create_embed("🔄 Загрузка", "Получаем информацию о треке...")
                    )
        elif response_method:
            loading_msg = await response_method(
                embed=create_embed("🔄 Загрузка", "Получаем информацию о треке...")
            )

        update_msg_method = loading_msg.edit if loading_msg and not edit_method else edit_method

        try:
            logger.info(f"Получение информации о потоке для: {url}")
            track_info = await get_stream_info(url)
            if not track_info:
                raise ValueError("Не удалось получить информацию о треке.")

            track = Track(track_info, requester)
            self.queue.append(track)
            logger.info(f"Трек добавлен в очередь: {track.title}")

            embed = create_embed(
                "✅ Трек добавлен",
                f"[{track.title}]({track.url})",
                COLORS["SUCCESS"],
                thumbnail=track.thumbnail,
                fields=[
                    ("Длительность", format_duration(track.duration), True),
                    ("Запросил", requester.mention, True),
                    ("Позиция", str(len(self.queue)), True),
                ],
            )

            if update_msg_method:
                await update_msg_method(content=None, embed=embed, view=None)
            elif response_method:
                await response_method(embed=embed)

            if not self.is_playing and self.voice_client and self.voice_client.is_connected():
                self.start_playback_loop()

        except Exception as e:
            logger.error(f"Ошибка при добавлении трека {url}: {e}", exc_info=True)
            error_embed = create_embed(
                "❌ Ошибка", f"Произошла ошибка при добавлении трека:\n`{e}`", COLORS["ERROR"]
            )
            if update_msg_method:
                await update_msg_method(content=None, embed=error_embed, view=None)
            elif response_method:
                await response_method(embed=error_embed)

    def start_playback_loop(self) -> None:
        """Запускает или перезапускает задачу асинхронного воспроизведения следующего трека.

        Гарантирует, что одновременно выполняется не более одной такой задачи.
        """
        if self._play_next_task and not self._play_next_task.done():
            logger.debug("Цикл воспроизведения уже запущен. Новая задача не создается.")
            return
        logger.info("Запуск нового цикла воспроизведения...")
        self._play_next_task = self.loop.create_task(self.play_next())

    async def play_next(self) -> None:
        """Основная логика воспроизведения следующего трека из очереди."""
        try:
            if not self.voice_client or not self.voice_client.is_connected():
                logger.warning("play_next: Голосовой клиент не подключен. Очистка и выход.")
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

            try:
                logger.info(f"Запуск конвейера yt-dlp | ffmpeg для: {self.current_track.title}")

                yt_dlp_args = [
                    "yt-dlp",
                    self.current_track.url,
                    "-f",
                    "bestaudio/best",
                    "-o",
                    "-",
                    "--quiet",
                    "--no-warnings",
                ]
                if PROXY_URL:
                    yt_dlp_args.extend(["--proxy", PROXY_URL])

                self.yt_process = subprocess.Popen(yt_dlp_args, stdout=subprocess.PIPE)

                ffmpeg_args = [
                    "ffmpeg",
                    "-i",
                    "-",
                    "-f",
                    "s16le",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-b:a",
                    "192k",
                    "-bufsize",
                    "2048k",
                    "-thread_queue_size",
                    "4096",
                    "-fflags",
                    "+genpts",
                    "-avoid_negative_ts",
                    "make_zero",
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                    "-loglevel",
                    "error",
                    "-vn",
                    "pipe:1",
                ]

                if self.yt_process.stdout is None:
                    raise IOError("Не удалось получить stdout от yt-dlp.")

                self.ffmpeg_process = subprocess.Popen(
                    ffmpeg_args, stdin=self.yt_process.stdout, stdout=subprocess.PIPE
                )

                if self.ffmpeg_process.stdout is None:
                    raise IOError("Не удалось получить stdout от ffmpeg.")

                source = discord.PCMAudio(self.ffmpeg_process.stdout)
                self.voice_client.play(
                    source, after=lambda e: self.loop.create_task(self._after_playback(e))
                )

                self.is_playing = True
                self.is_paused = False
                logger.info(f"Воспроизведение начато для: {self.current_track.title}")
                await self._update_now_playing_message()

            except Exception as e:
                logger.error(
                    f"Ошибка создания источника для трека '{self.current_track.title}': {e}",
                    exc_info=True,
                )
                await self.send_error_message(
                    f"Не удалось создать источник для трека '{self.current_track.title}'."
                )
                self.current_track = None
                self.start_playback_loop()

        except Exception as e:
            logger.error(f"Ошибка в цикле play_next: {e}", exc_info=True)
            await self.send_error_message("Произошла критическая ошибка в цикле воспроизведения.")
            await self.stop()

    async def _after_playback(self, error: Exception | None) -> None:
        """Callback-функция, вызываемая после завершения воспроизведения трека (или при ошибке).

        Обрабатывает ошибки, очищает текущий трек и запускает воспроизведение следующего,
        если он есть.

        Args:
            error: Ошибка, возникшая во время воспроизведения,
                или None, если трек завершился успешно.
        """
        logger.debug(f"_after_playback вызван. Ошибка: {error}")
        finished_track_title = (
            self.current_track.title if self.current_track else "Неизвестный трек"
        )
        self.is_playing = False
        self.current_track = None

        # Завершаем процессы
        if self.yt_process:
            try:
                self.yt_process.kill()
                self.yt_process.wait()
            except Exception as e:
                logger.warning(f"Не удалось завершить процесс yt-dlp: {e}")
            self.yt_process = None
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.kill()
                self.ffmpeg_process.wait()
            except Exception as e:
                logger.warning(f"Не удалось завершить процесс ffmpeg: {e}")
            self.ffmpeg_process = None

        if error:
            logger.error(
                f"Ошибка воспроизведения трека '{finished_track_title}': {error}", exc_info=error
            )
            await self.send_error_message(
                f"Ошибка во время воспроизведения трека '{finished_track_title}': `{error}`"
            )

        # Проверяем, есть ли еще треки в очереди и подключен ли клиент
        if self.queue and self.voice_client and self.voice_client.is_connected():
            logger.info("Запуск следующего трека из очереди.")
            self.start_playback_loop()
        elif self.voice_client and self.voice_client.is_connected():
            logger.info("Очередь пуста. Воспроизведение завершено, клиент остается подключенным.")
            # Не очищаем очередь здесь, если она пуста, cleanup это сделает при необходимости
            await self.cleanup(clear_queue=False)  # Очищаем сообщение "Сейчас играет" и т.д.
        else:  # Клиент не подключен (например, был отключен вручную во время after_playback)
            logger.info("Воспроизведение завершено и голосовой клиент уже отключен.")
            await self.cleanup(clear_queue=True)  # Полная очистка

    async def pause(self, interaction: discord.Interaction | None = None) -> None:
        """Приостанавливает воспроизведение текущего трека.

        Args:
            interaction: Опциональное взаимодействие для ответа пользователю.
        """
        if self.voice_client and self.is_playing and not self.is_paused:
            logger.info("Приостановка воспроизведения.")
            self.voice_client.pause()
            self.is_paused = True
            if interaction and not interaction.response.is_done():
                await interaction.response.send_message(
                    "⏸️ Воспроизведение приостановлено.", ephemeral=True
                )
            elif interaction:  # Если ответ уже был (например, из View)
                await interaction.followup.send(
                    "⏸️ Воспроизведение приостановлено.",
                    ephemeral=True,
                )
            await self._update_now_playing_message()
        elif interaction:
            msg = (
                "Сейчас ничего не играет."
                if not self.is_playing
                else "Воспроизведение уже на паузе."
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)

    async def resume(self, interaction: discord.Interaction | None = None) -> None:
        """Возобновляет воспроизведение приостановленного трека.

        Args:
            interaction: Опциональное взаимодействие для ответа пользователю.
        """
        if self.voice_client and self.is_paused:
            logger.info("Возобновление воспроизведения.")
            self.voice_client.resume()
            self.is_paused = False
            if interaction and not interaction.response.is_done():
                await interaction.response.send_message(
                    "▶️ Воспроизведение возобновлено.", ephemeral=True
                )
            elif interaction:
                await interaction.followup.send("▶️ Воспроизведение возобновлено.", ephemeral=True)
            await self._update_now_playing_message()
        elif interaction:
            msg = "Воспроизведение не на паузе."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)

    async def skip(self, interaction: discord.Interaction | None = None) -> None:
        """Пропускает текущий воспроизводимый трек.

        Args:
            interaction: Опциональное взаимодействие для ответа пользователю.
        """
        if self.voice_client and self.is_playing:
            skipped_title = self.current_track.title if self.current_track else "текущий трек"
            logger.info(f"Пропуск трека: {skipped_title}")
            self.voice_client.stop()  # Это вызовет _after_playback, который запустит следующий трек
            if interaction and not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⏭️ Трек '{skipped_title}' пропущен.", ephemeral=True
                )
            elif interaction:  # Если ответ уже был (например, из View)
                await interaction.followup.send(
                    f"⏭️ Трек '{skipped_title}' пропущен.", ephemeral=True
                )
        elif interaction:
            msg = "Сейчас ничего не играет, чтобы можно было пропустить."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)

    async def stop(self, interaction: discord.Interaction | None = None) -> None:
        """Полностью останавливает воспроизведение, очищает очередь и отключает бота.

        Args:
            interaction: Опциональное взаимодействие для ответа пользователю.
        """
        logger.info("Получена команда stop. Отключение плеера.")
        await self.disconnect(interaction)  # disconnect уже содержит логику ответа

    async def show_queue(self, interaction: discord.Interaction) -> None:
        """Отображает текущую очередь воспроизведения в виде эмбеда.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
        """
        if not self.current_track and not self.queue:
            await interaction.response.send_message(
                embed=create_embed("ℹ️ Очередь пуста", color=COLORS["INFO"]), ephemeral=True
            )
            return
        embed = discord.Embed(title="🎵 Очередь воспроизведения", color=COLORS["DEFAULT"])
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
            total_duration = sum(t.duration for t in queue_list if t.duration) + (
                self.current_track.duration
                if self.current_track and self.current_track.duration
                else 0
            )
            for i, track in enumerate(queue_list[:15], 1):
                name, value, _ = track.to_embed_field(index=i)
                description_lines.append(f"{name}\n{value}")
            if len(queue_list) > 15:
                description_lines.append(f"\n*...и еще {len(queue_list) - 15} трек(ов)*")
            embed.set_footer(
                text=(
                    f"Всего треков: {len(queue_list) + (1 if self.current_track else 0)} | "
                    f"Общая длительность: {format_duration(total_duration)}"
                )
            )
        elif self.current_track:
            embed.set_footer(
                text=(
                    f"Всего треков: 1 | "
                    f"Общая длительность: {format_duration(self.current_track.duration)}"
                )
            )
        embed.description = "\n".join(description_lines)[:4096]
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _update_now_playing_message(self) -> None:
        """Обновляет или отправляет сообщение "Сейчас играет".

        Сообщение содержит актуальную информацию о треке и кнопки управления.
        """
        if not self.text_channel:
            logger.warning(
                (
                    "_update_now_playing_message: text_channel не установлен, "
                    "сообщение не будет отправлено/обновлено."
                )
            )
            return

        # Локальный импорт для избежания циклических зависимостей
        from .ui import PlayerControlView  # (на уровне модуля)

        embed = self._create_now_playing_embed()

        # Создаем или получаем существующий view
        current_view = (
            self.player_view
            if self.player_view and not self.player_view.is_finished()
            else PlayerControlView(self)
        )
        if hasattr(current_view, "_update_buttons"):
            current_view._update_buttons()  # Обновляем состояние кнопок

        if self.now_playing_message:
            try:
                await self.now_playing_message.edit(embed=embed, view=current_view)
                logger.debug("Сообщение 'Сейчас играет' обновлено.")
            except discord.NotFound:
                logger.warning(
                    "Сообщение 'Сейчас играет' не найдено (возможно, удалено). Отправляем новое."
                )
                self.now_playing_message = None  # Сбрасываем, чтобы отправить новое
            except Exception as e:
                logger.error(
                    f"Не удалось отредактировать сообщение 'Сейчас играет': {e}", exc_info=True
                )
                self.now_playing_message = None  # Сбрасываем при ошибке редактирования

        if not self.now_playing_message:  # Если сообщение не было обновлено или его не было
            try:
                self.now_playing_message = await self.text_channel.send(
                    embed=embed, view=current_view
                )
                logger.info("Новое сообщение 'Сейчас играет' отправлено.")
            except (
                discord.HTTPException
            ) as e:  # Более конкретное исключение для сетевых ошибок Discord
                logger.error(
                    f"Не удалось отправить сообщение 'Сейчас играет' (HTTPException): {e}",
                    exc_info=True,
                )
                self.now_playing_message = None
            except Exception as e:
                logger.error(
                    f"Не удалось отправить сообщение 'Сейчас играет' (Общая ошибка): {e}",
                    exc_info=True,
                )
                self.now_playing_message = None

        self.player_view = current_view  # type: ignore
        # Сохраняем view для последующих обновлений или остановки

    def _create_now_playing_embed(self) -> discord.Embed:
        """Создает эмбед для сообщения "Сейчас играет"."""
        if not self.current_track:
            return create_embed("⏹️ Ничего не играет", color=COLORS["INFO"])
        track = self.current_track
        state = "⏸️ Пауза:" if self.is_paused else "▶️ Сейчас играет:"
        embed = create_embed(
            state, f"[{track.title}]({track.url})", COLORS["DEFAULT"], thumbnail=track.thumbnail
        )
        fields = [
            ("Длительность", format_duration(track.duration), True),
            ("Запросил", track.requester.mention, True),
        ]
        if track.uploader:
            uploader_text = (
                f"[{track.uploader}]({track.uploader_url})"
                if track.uploader_url
                else track.uploader
            )
            fields.append(("Автор", uploader_text, True))
        if self.queue:
            next_track = self.queue[0]
            fields.append(("Следующий", f"[{next_track.title}]({next_track.url})", False))
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
        return embed

    async def send_error_message(self, message: str) -> None:
        """Отправляет сообщение об ошибке в установленный текстовый канал плеера.

        Args:
            message: Текст ошибки для отображения.
        """
        if self.text_channel:
            try:
                await self.text_channel.send(
                    embed=create_embed("❌ Ошибка", message, COLORS["ERROR"])
                )
            except discord.HTTPException as e:
                logger.error(
                    (
                        f"Не удалось отправить сообщение об ошибке в текстовый канал "
                        f"(HTTPException): {e}"
                    )
                )
            except Exception as e:
                logger.error(
                    (
                        f"Не удалось отправить сообщение об ошибке в текстовый канал "
                        f"(Общая ошибка): {e}"
                    )
                )
        else:
            logger.warning(
                f"Невозможно отправить сообщение об ошибке (text_channel не установлен): {message}"
            )

    async def cleanup(self, clear_queue: bool = True) -> None:
        """Очищает состояние плеера: останавливает воспроизведение, сбрасывает текущий трек и т.д.

        Args:
            clear_queue: Если True, очередь треков будет очищена.
        """
        logger.debug(f"Вызвана очистка. clear_queue={clear_queue}")
        self.is_playing = False
        self.is_paused = False
        self.current_track = None
        if self.player_view and isinstance(self.player_view, discord.ui.View):
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
