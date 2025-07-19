"""Модуль, содержащий класс MusicPlayer для музыкального плеера V2."""

import asyncio
import logging

import discord
import yt_dlp

from .errors import TrackError, VoiceConnectionError
from .track import Track

logger = logging.getLogger("bot.utils.music_v2.player")

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class MusicPlayer:
    """Управляет воспроизведением музыки для одного сервера."""

    def __init__(self, bot: discord.Client, guild: discord.Guild, proxy: str | None = None) -> None:
        """Инициализирует музыкальный плеер.

        Args:
            bot: Экземпляр бота.
            guild: Сервер, к которому привязан плеер.
            proxy: URL прокси-сервера для использования.
        """
        self.bot = bot
        self.guild = guild
        self.proxy = proxy
        self.voice_client: discord.VoiceClient | None = None
        self.current_track: Track | None = None
        self.play_next_task: asyncio.Task | None = None
        self.loop = asyncio.get_event_loop()

    async def connect(self, channel: discord.VoiceChannel) -> None:
        """Подключает или перемещает бота в указанный голосовой канал.

        Args:
            channel: Голосовой канал для подключения.

        Raises:
            VoiceConnectionError: Если не удалось подключиться к каналу.
        """
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel == channel:
                return
            await self.voice_client.move_to(channel)
            logger.info(f"Переместились в канал: {channel.name}")
            return

        try:
            self.voice_client = await channel.connect(timeout=30.0)
            logger.info(f"Подключились к каналу: {channel.name}")
        except asyncio.TimeoutError:
            raise VoiceConnectionError(f"Таймаут при подключении к каналу {channel.name}.")
        except Exception as e:
            raise VoiceConnectionError(f"Не удалось подключиться к каналу {channel.name}: {e}")

    async def disconnect(self) -> None:
        """Отключает бота от голосового канала."""
        if self.voice_client:
            await self.voice_client.disconnect(force=True)
            self.voice_client = None
            logger.info("Отключились от голосового канала.")

    def is_playing(self) -> bool:
        """Проверяет, играет ли что-то в данный момент."""
        return self.voice_client is not None and self.voice_client.is_playing()

    async def play(self, track: Track) -> None:
        """Начинает воспроизведение трека.

        Args:
            track: Трек для воспроизведения.
        """
        if not self.voice_client:
            raise VoiceConnectionError("Плеер не подключен к голосовому каналу.")

        self.current_track = track
        logger.info(f"Начинаем воспроизведение: {track.title}")

        try:
            # Получаем URL аудиопотока прямо перед воспроизведением
            track_info = await self._get_stream_url(track.url)
            stream_url = track_info.get("url")
            if not stream_url:
                raise TrackError("Не удалось получить URL аудиопотока.")

            source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
            self.voice_client.play(source, after=self._after_playback)

        except (TrackError, yt_dlp.utils.DownloadError) as e:
            logger.error(f"Ошибка при получении потока для '{track.title}': {e}", exc_info=True)
            # В будущем здесь будет отправка сообщения об ошибке в чат
            self._after_playback(e)
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при воспроизведении '{track.title}': {e}", exc_info=True
            )
            self._after_playback(e)

    async def _get_stream_url(self, url: str) -> dict:
        """Получает URL аудиопотока с помощью yt-dlp."""
        ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "auto",
            "source_address": "0.0.0.0",
        }
        if self.proxy:
            ydl_opts["proxy"] = self.proxy

        ytdl = yt_dlp.YoutubeDL(ydl_opts)
        return await self.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

    def _after_playback(self, error: Exception | None) -> None:
        """Обрабатывает завершение воспроизведения трека.

        Args:
            error: Ошибка, если она произошла во время воспроизведения.
        """
        if error:
            logger.error(f"Ошибка во время воспроизведения: {error}", exc_info=error)

        logger.info("Воспроизведение завершено.")
        self.current_track = None
        # В будущем здесь будет запуск следующего трека из очереди
