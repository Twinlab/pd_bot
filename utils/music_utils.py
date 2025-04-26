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

logger = logging.getLogger("music")

DOWNLOADS_DIR = 'downloads' # Директория для скачивания
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

COLORS = { # Стандартные цвета для эмбедов
    'DEFAULT': discord.Color.blue(),
    'ERROR':   discord.Color.red(),
    'SUCCESS': discord.Color.green()
}

from config import load_config as load_main_config

# Загружаем конфигурацию для получения настроек yt-dlp (например, прокси)
_config = load_main_config()
# Опции для yt-dlp
YDL_OPTS = {
    'format': 'bestaudio/best',
    'outtmpl': f'{DOWNLOADS_DIR}/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True, # Скачивать только один трек, даже если ссылка на плейлист
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0', # Принудительно использовать IPv4
    'proxy': _config.get("PROXY_URL", None), # Использовать прокси из конфига, если задан
    # Настройки постпроцессора FFmpeg для извлечения аудио
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

def create_embed(title: str, description: str, color: discord.Color = COLORS['DEFAULT'], **kwargs: Any) -> discord.Embed:
    """
    Создает и возвращает объект discord.Embed с заданными параметрами.
    Поддерживает установку thumbnail, footer и полей через kwargs.
    """
    embed = discord.Embed(title=title, description=description, color=color)

    for name, value in kwargs.items():
        if not value:
            continue

        if name == 'thumbnail':
            embed.set_thumbnail(url=value)
        elif name == 'footer':
            embed.set_footer(text=value)
        # Добавление полей (ожидается список кортежей: (name, value, inline))
        elif name == 'fields':
            for field in value:
                embed.add_field(name=field[0], value=field[1], inline=field[2] if len(field) > 2 else True)
        # Добавление обычного поля (если ключ не 'thumbnail', 'footer' или 'fields')
        else:
            embed.add_field(name=name, value=value, inline=True)

    return embed

def format_duration(duration: Optional[Union[int, float, str]]) -> str:
    """
    Форматирует продолжительность из секунд в строку формата MM:SS или HH:MM:SS.
    Возвращает '∞' для потоков (duration=0 или None) и '?:??' при ошибке.
    """
    if not duration:
        return "∞" # Для потоков или неизвестной длительности

    try:
        duration = int(float(duration)) # Преобразуем в секунды
        # Рассчитываем часы, минуты, секунды
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "?:??" # При ошибке форматирования

class MusicPlayer:
    """
    Класс, управляющий состоянием воспроизведения музыки для одного сервера (гильдии).
    Хранит очередь треков, текущий трек, настройки громкости и т.д.
    Предоставляет методы для добавления, воспроизведения, пропуска треков и управления очередью.
    """
    def __init__(self, bot):
        """Инициализирует экземпляр плеера для конкретного сервера."""
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
        """Отправляет эмбед в контекст"""
        return await ctx.send(embed=create_embed(title, description, color, **kwargs))

    async def add_track(self, ctx, url_or_search):
        """Добавляет трек в очередь"""
        loading_message = await self.send_embed(ctx, "🔄 Загрузка", "Скачиваем трек...")

        try:
            track = await self._download_track(url_or_search, ctx.author)
            self.queue.append(track)

            # Обновляем сообщение о загрузке информацией о треке
            file_size = os.path.getsize(track['file']) / (1024 * 1024) if os.path.exists(track['file']) else 0
            position = len(self.queue)
            is_playing = ctx.guild.voice_client and ctx.guild.voice_client.is_playing()

            embed = create_embed(
                "✅ Трек добавлен",
                f"**[{track['title']}]({track['url']})**",
                COLORS['SUCCESS'],
                thumbnail=track['thumbnail'],
                fields=[
                    ("Файл", f"`{os.path.basename(track['file'])}` ({file_size:.2f} МБ)", True),
                    ("Длительность", format_duration(track['duration']), True),
                    ("Запросил", track['requester'].mention, True)
                ],
                footer=f"Позиция в очереди: {position}" if position > 1 or (position == 1 and is_playing) else None
            )

            await loading_message.edit(embed=embed)
            self.text_channel = ctx.channel # Запоминаем канал для сообщений плеера

            # Начинаем воспроизведение, если бот в канале и ничего не играет
            voice_client = ctx.guild.voice_client
            if not voice_client or not voice_client.is_playing():
                await self.play_next(ctx.guild)

            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении трека: {e}", exc_info=True)
            await loading_message.edit(
                embed=create_embed("❌ Ошибка", f"Не удалось добавить трек: {str(e)[:900]}", COLORS['ERROR'])
            )
            return False

    async def _download_track(self, url, requester):
        """Скачивает трек и возвращает информацию о нем"""
        ytdl = yt_dlp.YoutubeDL(YDL_OPTS)

        # Запускаем скачивание и извлечение информации в отдельном потоке
        info = await self.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=True))

        # Если был поиск, берем первый результат
        if 'entries' in info:
            info = info['entries'][0]

        # Определяем ожидаемое имя файла после скачивания и конвертации
        filename = ytdl.prepare_filename(info)
        base_filename = os.path.splitext(filename)[0]

        # Ищем скачанный файл (с учетом возможной конвертации в mp3)
        audio_file = None
        for ext in ['.mp3', '.opus', '.m4a', '.webm']:
            if os.path.exists(f"{base_filename}{ext}"):
                audio_file = f"{base_filename}{ext}"
                break

        # Если файл с ожидаемым расширением не найден, пробуем найти через glob
        if not audio_file:
            matching_files = glob.glob(f"{base_filename}.*")
            audio_file = matching_files[0] if matching_files else None

        if not audio_file:
            raise FileNotFoundError(f"Скачанный аудиофайл не найден: {base_filename}.*")

        if os.path.getsize(audio_file) == 0:
            raise ValueError(f"Скачанный файл имеет нулевой размер: {audio_file}")

        # Возвращаем словарь с информацией о треке
        return {
            'file': audio_file,
            'title': info.get('title', 'Unknown title'),
            'url': info.get('webpage_url', info.get('url')),
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail'),
            'requester': requester,
            'uploader': info.get('uploader', 'Unknown uploader'),
            'uploader_url': info.get('uploader_url'),
            'id': info.get('id', '')
        }

    async def play_next(self, guild):
        """Воспроизводит следующий трек из очереди"""
        if self.is_playing_next:
            return

        self.is_playing_next = True

        try:
            self.skip_votes.clear() # Сбрасываем голоса за пропуск
            voice_client = guild.voice_client

            if not voice_client: # Если бот не в голосовом канале
                self.is_playing_next = False
                return

            # Если очередь пуста
            if not self.queue:
                # Удаляем сообщение "Сейчас играет"
                if self.now_playing_message:
                    try:
                        await self.now_playing_message.delete()
                    except:
                        pass # Игнорируем ошибку, если сообщение уже удалено
                self.now_playing_message = None
                self.current = None # Сбрасываем текущий трек

                # Отправляем сообщение о пустой очереди
                if self.text_channel:
                    await self.text_channel.send(
                        embed=create_embed(
                            "🎵 Очередь завершена",
                            "Очередь пуста. Добавьте треки командой `/play`",
                            COLORS['DEFAULT']
                        )
                    )

                self.is_playing_next = False
                return

            track = self.queue.popleft() # Берем следующий трек из очереди
            self.current = track

            # Проверяем доступность файла трека
            file_path = track['file']
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise FileNotFoundError(f"Файл трека недоступен или поврежден: {file_path}")

            # Создаем аудио источник
            logger.info(f"Создание FFmpegPCMAudio для файла: {file_path}")
            try:
                # Опции FFmpeg можно передать здесь, если нужно (например, для отладки)
                # options = '-loglevel debug'
                # audio = discord.FFmpegPCMAudio(file_path, options=options)
                audio = discord.FFmpegPCMAudio(file_path)
                source = discord.PCMVolumeTransformer(audio, volume=self.volume) # Для управления громкостью
                logger.info(f"Аудио источник FFmpegPCMAudio создан успешно.")
            except Exception as audio_error:
                logger.error(f"Ошибка при создании FFmpegPCMAudio: {audio_error}", exc_info=True)
                # Сообщаем пользователю об ошибке, связанной с FFmpeg
                if self.text_channel:
                    await self.text_channel.send(
                        embed=create_embed(
                            "❌ Ошибка FFmpeg",
                            f"Не удалось обработать аудиофайл. Убедитесь, что FFmpeg установлен и доступен.\nОшибка: `{audio_error}`",
                            COLORS['ERROR']
                        )
                    )
                raise # Передаем ошибку выше для обработки

            # Callback-функция, вызываемая discord.py после завершения трека
            def after_playback(error):
                # Сохраняем путь к файлу, который только что закончился
                finished_track_path = track.get('file')

                if error:
                    logger.error(f"Ошибка во время воспроизведения (в callback after_playback): {error}")

                # Запускаем следующий трек асинхронно
                future = asyncio.run_coroutine_threadsafe(self.play_next(guild), self.loop)
                try:
                    future.result(timeout=30) # Ожидаем недолго, чтобы убедиться в запуске
                except Exception as e:
                    logger.error(f"Ошибка при ожидании запуска play_next из after_playback: {e}")
                finally:
                    # Пытаемся удалить файл завершенного трека
                    if finished_track_path and os.path.exists(finished_track_path):
                        try:
                            os.remove(finished_track_path)
                            logger.info(f"Удален файл: {finished_track_path}")
                        except Exception as delete_error:
                            logger.error(f"Не удалось удалить файл {finished_track_path}: {delete_error}")

            # Начинаем воспроизведение текущего трека
            logger.info(f"Вызов voice_client.play() для трека: {track.get('title', 'Unknown')}")
            voice_client.play(source, after=after_playback)
            logger.info(f"Воспроизведение трека запущено.")

            # Отправляем сообщение "Сейчас играет"
            if self.text_channel:
                # Удаляем предыдущее сообщение "Сейчас играет", если оно было
                if self.now_playing_message:
                    try:
                        await self.now_playing_message.delete()
                    except:
                        pass # Игнорируем, если сообщение уже удалено

                # Создаем и отправляем новое сообщение "Сейчас играет"
                embed = self._create_now_playing_embed()
                self.now_playing_message = await self.text_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Ошибка при воспроизведении: {e}", exc_info=True)

            if self.text_channel:
                await self.text_channel.send(
                    embed=create_embed("❌ Ошибка", f"Ошибка воспроизведения: {str(e)[:900]}", COLORS['ERROR'])
                )

            # Пробуем следующий трек
            await asyncio.sleep(1) # Небольшая пауза перед попыткой следующего трека
            asyncio.create_task(self.play_next(guild)) # Запускаем асинхронно

        finally:
            self.is_playing_next = False

    def _create_now_playing_embed(self):
        """Создает эмбед для текущего трека"""
        if not self.current:
            return create_embed("Ничего не играет", "Добавьте треки в очередь")

        track = self.current
        fields = [
            ("Длительность", format_duration(track['duration']), True),
            ("Запросил", track['requester'].mention, True)
        ]

        # Добавляем информацию об авторе
        if track['uploader']:
            uploader_text = f"[{track['uploader']}]({track['uploader_url']})" if track['uploader_url'] else track['uploader']
            fields.append(("Автор", uploader_text, True))

        # Добавляем информацию о следующем треке
        if self.queue:
            fields.append((
                f"Следующий трек (очередь: {len(self.queue)})",
                f"**{self.queue[0]['title']}**",
                False
            ))

        return create_embed(
            "🎵 Сейчас играет",
            f"**[{track['title']}]({track['url']})**",
            COLORS['DEFAULT'],
            thumbnail=track['thumbnail'],
            fields=fields
        )

    async def skip_track(self, ctx):
        """Пропускает текущий трек"""
        voice_client = ctx.guild.voice_client

        if not voice_client or not voice_client.is_playing():
            await self.send_embed(ctx, "❌ Ошибка", "Ничего не воспроизводится", COLORS['ERROR'])
            return False

        # Проверяем, есть ли у пользователя права на немедленный пропуск (DJ или запросивший трек)
        is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
        is_requester = self.current and self.current['requester'].id == ctx.author.id

        # Если есть права - пропускаем
        if is_dj or is_requester:
            await self.send_embed(ctx, "⏭️ Трек пропущен", f"Трек пропущен по запросу {ctx.author.mention}", COLORS['SUCCESS'])
            voice_client.stop()
            return True

        # Иначе запускаем систему голосования
        channel_members = len([m for m in voice_client.channel.members if not m.bot]) # Считаем реальных пользователей
        required_votes = math.ceil(channel_members / 2) # Нужно больше половины голосов

        # Проверяем, голосовал ли пользователь уже
        if ctx.author.id in self.skip_votes:
            await self.send_embed(
                ctx, "⏭️ Голосование",
                f"Вы уже голосовали!\nГолосов: {len(self.skip_votes)}/{required_votes}",
                COLORS['DEFAULT']
            )
            return False

        self.skip_votes.add(ctx.author.id) # Добавляем голос пользователя

        # Проверяем, набралось ли достаточно голосов
        if len(self.skip_votes) >= required_votes:
            await self.send_embed(
                ctx, "⏭️ Трек пропущен",
                f"Трек пропущен по голосованию ({len(self.skip_votes)}/{required_votes})",
                COLORS['SUCCESS']
            )
            voice_client.stop()
            return True
        else:
            await self.send_embed(
                ctx, "⏭️ Голосование",
                f"{ctx.author.mention} проголосовал за пропуск\nГолосов: {len(self.skip_votes)}/{required_votes}",
                COLORS['DEFAULT']
            )
            return False

    async def stop_playback(self, ctx):
        """Останавливает воспроизведение и очищает очередь"""
        voice_client = ctx.guild.voice_client

        if not voice_client:
            await self.send_embed(ctx, "❌ Ошибка", "Бот не подключен к голосовому каналу", COLORS['ERROR'])
            return False

        # Очищаем очередь и останавливаем воспроизведение
        self.queue.clear()
        self.is_paused = False
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        # Отключаем бота от голосового канала
        await voice_client.disconnect()

        # Пытаемся удалить файл текущего трека (если он был)
        if self.current and self.current.get('file') and os.path.exists(self.current['file']):
             try:
                 os.remove(self.current['file'])
                 logger.info(f"Удален файл текущего трека при остановке: {self.current['file']}")
             except Exception as delete_error:
                 logger.error(f"Не удалось удалить файл {self.current['file']} при остановке: {delete_error}")

        # Сбрасываем состояние плеера
        if self.now_playing_message:
            try:
                await self.now_playing_message.delete()
            except:
                pass
        self.now_playing_message = None
        self.current = None

        await self.send_embed(
            ctx, "⏹️ Остановлено",
            "Воспроизведение остановлено, очередь очищена",
            COLORS['SUCCESS']
        )
        return True

    async def pause_resume(self, ctx, pause=True):
        """Ставит на паузу или возобновляет воспроизведение"""
        voice_client = ctx.guild.voice_client

        # Проверки состояния
        if not voice_client:
            await self.send_embed(ctx, "❌ Ошибка", "Бот не подключен к голосовому каналу", COLORS['ERROR'])
            return False

        if pause and (not voice_client.is_playing() or voice_client.is_paused()):
            await self.send_embed(ctx, "❌ Ошибка", "Нет активного воспроизведения", COLORS['ERROR'])
            return False

        if not pause and not voice_client.is_paused():
            await self.send_embed(ctx, "❌ Ошибка", "Воспроизведение не на паузе", COLORS['ERROR'])
            return False

        # Выполняем паузу или возобновление
        if pause:
            voice_client.pause()
            self.is_paused = True
            await self.send_embed(ctx, "⏸️ Пауза", "Воспроизведение приостановлено", COLORS['DEFAULT'])
        else:
            voice_client.resume()
            self.is_paused = False
            await self.send_embed(ctx, "▶️ Продолжение", "Воспроизведение возобновлено", COLORS['SUCCESS'])

        return True

    async def show_queue(self, ctx, items_per_page=10):
        """Показывает очередь воспроизведения"""
        if not self.queue and not self.current:
            await self.send_embed(ctx, "Очередь пуста", "Добавьте треки командой `/play`", COLORS['ERROR'])
            return

        description = []

        # Информация о текущем треке
        if self.current:
            requester = self.current['requester'].mention
            duration = format_duration(self.current['duration'])
            description.append(f"**🎵 Сейчас играет:**\n[{self.current['title']}]({self.current['url']}) | {duration} | {requester}\n")

        # Информация о треках в очереди
        if self.queue:
            description.append("**⏱️ В очереди:**")

            for i, track in enumerate(list(self.queue)[:items_per_page], 1):
                requester = track['requester'].mention
                duration = format_duration(track['duration'])
                description.append(f"{i}. [{track['title']}]({track['url']}) | {duration} | {requester}")

            # Если треков больше, чем помещается на страницу
            if len(self.queue) > items_per_page:
                remaining = len(self.queue) - items_per_page
                description.append(f"\n*...и еще {remaining} трек(ов)*")

        await self.send_embed(
            ctx, "🎵 Очередь воспроизведения",
            "\n".join(description),
            footer=f"Всего треков: {len(self.queue) + (1 if self.current else 0)}"
        )

    async def remove_from_queue(self, ctx, position):
        """Удаляет трек из очереди по указанной позиции."""
        # Проверка наличия очереди и корректности позиции
        if not self.queue:
            await self.send_embed(ctx, "❌ Ошибка", "Очередь пуста", COLORS['ERROR'])
            return False

        if not (1 <= position <= len(self.queue)):
            await self.send_embed(
                ctx, "❌ Ошибка",
                f"Позиция должна быть от 1 до {len(self.queue)}",
                COLORS['ERROR']
            )
            return False

        track = list(self.queue)[position - 1] # Получаем трек по индексу (position - 1)

        # Проверяем права на удаление (DJ или запросивший)
        is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
        is_requester = track['requester'].id == ctx.author.id

        if not (is_dj or is_requester):
            await self.send_embed(
                ctx, "❌ Ошибка",
                "Вы можете удалить только запрошенный вами трек или иметь роль DJ",
                COLORS['ERROR']
            )
            return False

        del self.queue[position - 1] # Удаляем трек из очереди

        await self.send_embed(
            ctx, "🗑️ Трек удален",
            f"Трек **{track['title']}** удален из очереди",
            COLORS['SUCCESS']
        )
        return True

    async def search_tracks(self, ctx, query, max_results=5):
        """Ищет треки и позволяет пользователю выбрать из результатов"""
        loading_message = await self.send_embed(ctx, "🔍 Поиск", f"Ищу `{query}` на YouTube...")

        try:
            # Настройки для поиска
            search_opts = YDL_OPTS.copy()
            search_opts['default_search'] = f'ytsearch{max_results}'
            search_opts['extract_flat'] = True
            search_opts['quiet'] = True

            # Выполняем поиск
            ytdl = yt_dlp.YoutubeDL(search_opts)
            info = await self.loop.run_in_executor(
                None, lambda: ytdl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            )

            # Проверяем результаты
            if not info or not info.get('entries'):
                await loading_message.edit(
                    embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` ничего не найдено", COLORS['ERROR'])
                )
                return

            # Фильтруем результаты
            valid_entries = [entry for entry in info['entries'] if entry is not None]

            if not valid_entries:
                await loading_message.edit(
                    embed=create_embed("❌ Ничего не найдено", f"По запросу `{query}` нет доступных результатов", COLORS['ERROR'])
                )
                return

            # Формируем сообщение с результатами поиска для выбора
            description = "Выберите трек, отправив его номер (или 'отмена'):"
            fields = []
            for i, entry in enumerate(valid_entries, 1):
                title = entry.get('title', 'Неизвестно')
                uploader = entry.get('uploader', 'Неизвестно')
                duration = format_duration(entry.get('duration', 0))
                fields.append((f"{i}. {title}", f"Автор: {uploader} | Длительность: {duration}", False))

            await loading_message.edit(
                embed=create_embed(f"🔍 Результаты поиска '{query}'", description, fields=fields)
            )

            # Ожидаем ответ пользователя с выбором номера трека
            try:
                response = await self.bot.wait_for(
                    'message',
                    check=lambda m: (
                        m.author == ctx.author and
                        m.channel == ctx.channel and
                        (m.content.lower() in ['отмена', 'cancel'] or
                        (m.content.isdigit() and 1 <= int(m.content) <= len(valid_entries)))
                    ),
                    timeout=30 # Время ожидания ответа
                )

                if response.content.lower() in ['отмена', 'cancel']:
                    await self.send_embed(ctx, "🚫 Отменено", "Поиск отменен", COLORS['DEFAULT'])
                    return

                # Пользователь выбрал номер трека
                choice = int(response.content) - 1
                selected = valid_entries[choice]

                # Получаем URL выбранного трека и добавляем его в очередь
                url = selected.get('url', selected.get('webpage_url'))
                if not url:
                    await self.send_embed(ctx, "❌ Ошибка", "Не удалось получить URL для выбранного трека", COLORS['ERROR'])
                    return

                await self.add_track(ctx, url)

            except asyncio.TimeoutError:
                await self.send_embed(ctx, "⏱️ Время истекло", "Вы не выбрали трек вовремя", COLORS['ERROR'])

        except Exception as e:
            logger.error(f"Ошибка при поиске треков: {e}", exc_info=True)
            await loading_message.edit(embed=create_embed("❌ Ошибка", f"Ошибка при поиске: {str(e)[:900]}", COLORS['ERROR']))

async def ensure_voice(ctx):
    """Проверяет и обеспечивает голосовое подключение"""
    if not ctx.author.voice:
        await ctx.send(embed=create_embed("❌ Ошибка", "Вы должны быть в голосовом канале", COLORS['ERROR']))
        return False

    # Подключаемся к каналу пользователя или перемещаемся, если бот уже в другом канале
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await ctx.author.voice.channel.connect()
    elif voice_client.channel != ctx.author.voice.channel:
        await voice_client.move_to(ctx.author.voice.channel)

    return True

async def handle_play(ctx, query):
    """Обрабатывает команду воспроизведения: проверяет канал, добавляет трек/ищет."""
    if not query:
        await ctx.send(embed=create_embed("❌ Ошибка", "Укажите запрос или ссылку для воспроизведения", COLORS['ERROR']))
        return

    if not await ensure_voice(ctx):
        return

    # Получаем экземпляр плеера из кога
    player = getattr(ctx.cog, 'player', None)
    if not player:
         await ctx.send("Ошибка: Экземпляр плеера не найден.")
         return
    if query.startswith(('http://', 'https://')):
        await player.add_track(ctx, query)
    else:
        await player.search_tracks(ctx, query)

async def handle_skip(ctx):
    """Пропускает текущий трек"""
    player = getattr(ctx.cog, 'player', None)
    if player: await player.skip_track(ctx)
    else: await ctx.send("Ошибка: Экземпляр плеера не найден.")

async def handle_stop(ctx):
    """Останавливает воспроизведение и очищает очередь"""
    player = getattr(ctx.cog, 'player', None)
    if player: await player.stop_playback(ctx)
    else: await ctx.send("Ошибка: Экземпляр плеера не найден.")

async def handle_pause(ctx):
    """Ставит воспроизведение на паузу"""
    player = getattr(ctx.cog, 'player', None)
    if player: await player.pause_resume(ctx, pause=True)
    else: await ctx.send("Ошибка: Экземпляр плеера не найден.")

async def handle_resume(ctx):
    """Возобновляет воспроизведение"""
    player = getattr(ctx.cog, 'player', None)
    if player: await player.pause_resume(ctx, pause=False)
    else: await ctx.send("Ошибка: Экземпляр плеера не найден.")

async def handle_remove(ctx, position):
    """Удаляет трек из очереди по позиции"""
    player = getattr(ctx.cog, 'player', None)
    if player: await player.remove_from_queue(ctx, position)
    else: await ctx.send("Ошибка: Экземпляр плеера не найден.")

async def handle_queue(ctx):
    """Показывает очередь воспроизведения"""
    player = getattr(ctx.cog, 'player', None)
    if player: await player.show_queue(ctx)
    else: await ctx.send("Ошибка: Экземпляр плеера не найден.")

async def cleanup_player(player: 'MusicPlayer', guild_name: str):
    """Очищает состояние плеера: очередь, текущий трек, сообщение 'сейчас играет'."""
    if not player:
        logger.warning("Попытка очистить несуществующий плеер.")
        return

    # Пытаемся удалить файл текущего трека
    if player.current and player.current.get('file') and os.path.exists(player.current['file']):
         try:
             os.remove(player.current['file'])
             logger.info(f"Удален файл текущего трека при очистке плеера: {player.current['file']}")
         except Exception as delete_error:
             logger.error(f"Не удалось удалить файл {player.current['file']} при очистке плеера: {delete_error}")

         # Сбрасываем состояние плеера
         player.queue.clear()
         player.current = None
         player.is_paused = False

         # Удаляем сообщение "Сейчас играет"
    if player.now_playing_message:
        try:
            await player.now_playing_message.delete()
        except:
            pass
        player.now_playing_message = None

    logger.info(f"Плеер очищен для сервера {guild_name}")

async def auto_disconnect(player: 'MusicPlayer', guild: discord.Guild, voice_channel: discord.VoiceChannel):
    """Автоматически отключает бота, если он остался один в канале."""
    if not player:
        logger.warning(f"Попытка автоотключения для несуществующего плеера в {guild.name}")
        return

    # Отправляем сообщение об автоотключении в текстовый канал плеера
    if player.text_channel:
        try:
            await player.text_channel.send(
                embed=create_embed(
                    "👋 Автоотключение",
                    "Все пользователи покинули голосовой канал. Бот отключается.",
                    COLORS['DEFAULT']
                )
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения об автоотключении: {e}")

    # Отключаем бота от голосового канала
    try:
        if guild.voice_client:
            await guild.voice_client.disconnect()
    except Exception as e:
        logger.error(f"Ошибка при отключении от голосового канала: {e}")

    # Очищаем состояние плеера (очередь, текущий трек и т.д.)
    await cleanup_player(player, guild.name)

    logger.info(f"Бот автоматически отключен от канала {voice_channel.name}")
