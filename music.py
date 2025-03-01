import discord
import asyncio
import logging
import os
import math
import yt_dlp
import json
from collections import deque
import glob
from enum import Enum

# Настройка логирования
logger = logging.getLogger("music")

# Директория для загрузок
DOWNLOADS_DIR = 'downloads'
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Цвета для эмбедов
COLORS = {
    'DEFAULT': 0x3498db,
    'ERROR': 0xe74c3c,
    'SUCCESS': 0x2ecc71
}

# Загрузка конфигурации
def load_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return {}

config = load_config()

# Настройки для yt-dlp
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
    'proxy': config.get("PROXY_URL", None),
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

# Состояния трека
class TrackState(Enum):
    PLAYING = 1
    PAUSED = 2
    STOPPED = 3

# Единый экземпляр плеера
player = None

def get_player(bot):
    """Получает или создает экземпляр музыкального плеера"""
    global player
    if player is None:
        player = MusicPlayer(bot)
    return player

def create_embed(title, description, color=COLORS['DEFAULT'], **kwargs):
    """Создает эмбед-сообщение с заданными параметрами"""
    embed = discord.Embed(title=title, description=description, color=color)
    
    for name, value in kwargs.items():
        if not value:  # Пропускаем пустые значения
            continue
            
        if name == 'thumbnail':
            embed.set_thumbnail(url=value)
        elif name == 'footer':
            embed.set_footer(text=value)
        elif name == 'fields':
            for field in value:
                embed.add_field(name=field[0], value=field[1], inline=field[2] if len(field) > 2 else True)
        else:
            embed.add_field(name=name, value=value, inline=True)
    
    return embed

def format_duration(duration):
    """Форматирует продолжительность из секунд в MM:SS или HH:MM:SS"""
    if not duration:
        return "∞"  # Для стримов
    
    try:
        duration = int(float(duration))
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "?:??"  # Неизвестная продолжительность

class MusicPlayer:
    """Класс для управления музыкой на сервере"""

    def __init__(self, bot):
        self.bot = bot
        self.queue = deque()  # Очередь треков
        self.current = None   # Текущий трек
        self.volume = 0.5     # Громкость (0.0 - 1.0)
        self.text_channel = None  # Текстовый канал для сообщений
        self.now_playing_message = None  # Сообщение "Сейчас играет"
        self.skip_votes = set()  # Голоса за пропуск
        self.loop = asyncio.get_event_loop()  # Event loop для асинхронных задач
        self.is_playing_next = False  # Флаг для предотвращения одновременного запуска play_next
        self.cache = {}  # Кеш для поиска

    def clear_votes(self):
        """Очищает голоса за пропуск"""
        self.skip_votes.clear()

    async def send_embed(self, ctx, title, description, color=COLORS['DEFAULT'], **kwargs):
        """Отправляет эмбед в контекст"""
        embed = create_embed(title, description, color, **kwargs)
        return await ctx.send(embed=embed)

    async def add_track(self, ctx, url_or_search):
        """Добавляет трек в очередь"""
        loading_message = await self.send_embed(ctx, "🔄 Загрузка", "Скачиваем трек...")
        
        try:
            # Скачиваем трек
            track = await self._download_track(url_or_search, ctx.author)
            
            # Добавляем в очередь
            self.queue.append(track)
            
            # Обновляем сообщение
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
            
            # Сохраняем текстовый канал
            self.text_channel = ctx.channel
            
            # Начинаем воспроизведение если нужно
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
        
        # Скачиваем информацию и файл
        info = await self.loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=True)
        )
        
        # Обрабатываем результаты поиска
        if 'entries' in info:
            info = info['entries'][0]
        
        # Находим скачанный файл
        filename = ytdl.prepare_filename(info)
        base_filename = os.path.splitext(filename)[0]
        
        # Ищем файл с любым поддерживаемым расширением
        audio_file = None
        for ext in ['.mp3', '.opus', '.m4a', '.webm']:
            if os.path.exists(f"{base_filename}{ext}"):
                audio_file = f"{base_filename}{ext}"
                break
        
        # Проверяем существование файла
        if not audio_file or not os.path.exists(audio_file):
            # Ищем с помощью glob в случае изменения имени
            matching_files = glob.glob(f"{base_filename}.*")
            audio_file = matching_files[0] if matching_files else None
            
        if not audio_file:
            raise FileNotFoundError(f"Скачанный файл не найден: {base_filename}.*")
        
        # Проверяем размер файла
        if os.path.getsize(audio_file) == 0:
            raise ValueError(f"Файл имеет нулевой размер: {audio_file}")
        
        # Создаем трек
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
        # Предотвращаем параллельный запуск
        if self.is_playing_next:
            return
        
        self.is_playing_next = True
        
        try:
            # Сбрасываем голоса и проверяем подключение
            self.clear_votes()
            voice_client = guild.voice_client
            
            if not voice_client:
                self.is_playing_next = False
                return
            
            # Проверяем наличие треков в очереди
            if not self.queue:
                # Очищаем состояние
                if self.now_playing_message:
                    try:
                        await self.now_playing_message.delete()
                    except:
                        pass
                self.now_playing_message = None
                self.current = None
                
                # Отправляем сообщение о завершении
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
            
            # Получаем следующий трек
            track = self.queue.popleft()
            self.current = track
            
            # Проверяем файл
            file_path = track['file']
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise FileNotFoundError(f"Файл трека недоступен или поврежден: {file_path}")
            
            # Создаем аудио источник
            audio = discord.FFmpegPCMAudio(file_path)
            source = discord.PCMVolumeTransformer(audio, volume=self.volume)
            
            # Функция обратного вызова после завершения трека
            def after_playback(error):
                if error:
                    logger.error(f"Ошибка воспроизведения: {error}")
                
                # Запускаем следующий трек через event loop
                future = asyncio.run_coroutine_threadsafe(self.play_next(guild), self.loop)
                try:
                    future.result(timeout=30)
                except Exception as e:
                    logger.error(f"Ошибка при запуске следующего трека: {e}")
            
            # Начинаем воспроизведение
            voice_client.play(source, after=after_playback)
            
            # Отправляем сообщение
            if self.text_channel:
                embed = self._create_now_playing_embed()
                
                # Удаляем старое сообщение
                if self.now_playing_message:
                    try:
                        await self.now_playing_message.delete()
                    except:
                        pass
                
                self.now_playing_message = await self.text_channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Ошибка при воспроизведении: {e}", exc_info=True)
            
            if self.text_channel:
                await self.text_channel.send(
                    embed=create_embed("❌ Ошибка", f"Ошибка воспроизведения: {str(e)[:900]}", COLORS['ERROR'])
                )
            
            # Пробуем следующий трек
            await asyncio.sleep(1)
            asyncio.create_task(self.play_next(guild))
        
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
        
        # Добавляем информацию о авторе
        if track['uploader']:
            uploader_text = f"[{track['uploader']}]({track['uploader_url']})" if track['uploader_url'] else track['uploader']
            fields.append(("Автор", uploader_text, True))
        
        # Добавляем информацию о следующем треке
        if self.queue:
            next_track = self.queue[0]
            fields.append((
                f"Следующий трек (очередь: {len(self.queue)})",
                f"**{next_track['title']}**",
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
        
        # Проверяем права на пропуск
        is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
        is_requester = self.current and self.current['requester'].id == ctx.author.id
        
        # Если есть права - пропускаем сразу
        if is_dj or is_requester:
            await self.send_embed(ctx, "⏭️ Трек пропущен", f"Трек пропущен по запросу {ctx.author.mention}", COLORS['SUCCESS'])
            voice_client.stop()
            return True
        
        # Иначе голосование
        channel_members = len([m for m in voice_client.channel.members if not m.bot])
        required_votes = math.ceil(channel_members / 2)
        
        # Если уже голосовал
        if ctx.author.id in self.skip_votes:
            await self.send_embed(
                ctx,
                "⏭️ Голосование", 
                f"Вы уже голосовали!\nГолосов: {len(self.skip_votes)}/{required_votes}",
                COLORS['DEFAULT']
            )
            return False
        
        # Добавляем голос
        self.skip_votes.add(ctx.author.id)
        
        # Проверяем достаточно ли голосов
        if len(self.skip_votes) >= required_votes:
            await self.send_embed(
                ctx,
                "⏭️ Трек пропущен", 
                f"Трек пропущен по голосованию ({len(self.skip_votes)}/{required_votes})",
                COLORS['SUCCESS']
            )
            voice_client.stop()
            return True
        else:
            await self.send_embed(
                ctx,
                "⏭️ Голосование", 
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
        
        # Останавливаем и очищаем
        self.queue.clear()
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        
        # Отключаемся
        await voice_client.disconnect()
        
        # Очищаем состояние
        if self.now_playing_message:
            try:
                await self.now_playing_message.delete()
            except:
                pass
        self.now_playing_message = None
        self.current = None
        
        await self.send_embed(
            ctx,
            "⏹️ Остановлено", 
            "Воспроизведение остановлено, очередь очищена",
            COLORS['SUCCESS']
        )
        return True
    
    async def pause_resume(self, ctx, pause=True):
        """Ставит на паузу или возобновляет воспроизведение"""
        voice_client = ctx.guild.voice_client
        
        # Проверяем состояние
        if not voice_client:
            await self.send_embed(ctx, "❌ Ошибка", "Бот не подключен к голосовому каналу", COLORS['ERROR'])
            return False
            
        if pause and (not voice_client.is_playing() or voice_client.is_paused()):
            await self.send_embed(ctx, "❌ Ошибка", "Нет активного воспроизведения", COLORS['ERROR'])
            return False
            
        if not pause and not voice_client.is_paused():
            await self.send_embed(ctx, "❌ Ошибка", "Воспроизведение не на паузе", COLORS['ERROR'])
            return False
        
        # Ставим на паузу или возобновляем
        if pause:
            voice_client.pause()
            await self.send_embed(ctx, "⏸️ Пауза", "Воспроизведение приостановлено", COLORS['DEFAULT'])
        else:
            voice_client.resume()
            await self.send_embed(ctx, "▶️ Продолжение", "Воспроизведение возобновлено", COLORS['SUCCESS'])
            
        return True
    
    async def show_queue(self, ctx, items_per_page=10):
        """Показывает очередь воспроизведения"""
        if not self.queue and not self.current:
            await self.send_embed(ctx, "Очередь пуста", "Добавьте треки командой `/play`", COLORS['ERROR'])
            return
        
        # Строим описание
        description = ""
        
        # Текущий трек
        if self.current:
            requester = self.current['requester'].mention
            duration = format_duration(self.current['duration'])
            description += f"**🎵 Сейчас играет:**\n[{self.current['title']}]({self.current['url']}) | {duration} | {requester}\n\n"
        
        # Треки в очереди
        if self.queue:
            description += "**⏱️ В очереди:**\n"
            
            for i, track in enumerate(list(self.queue)[:items_per_page], 1):
                requester = track['requester'].mention
                duration = format_duration(track['duration'])
                description += f"{i}. [{track['title']}]({track['url']}) | {duration} | {requester}\n"
            
            # Если есть еще треки
            if len(self.queue) > items_per_page:
                remaining = len(self.queue) - items_per_page
                description += f"\n*...и еще {remaining} трек(ов)*"
        
        await self.send_embed(
            ctx,
            f"🎵 Очередь воспроизведения",
            description,
            footer=f"Всего треков: {len(self.queue) + (1 if self.current else 0)}"
        )
    
    async def remove_from_queue(self, ctx, position):
        """Удаляет трек из очереди по позиции"""
        # Проверяем позицию
        if not self.queue:
            await self.send_embed(ctx, "❌ Ошибка", "Очередь пуста", COLORS['ERROR'])
            return False
            
        if not (1 <= position <= len(self.queue)):
            await self.send_embed(
                ctx, 
                "❌ Ошибка", 
                f"Позиция должна быть от 1 до {len(self.queue)}", 
                COLORS['ERROR']
            )
            return False
        
        # Получаем трек
        track = list(self.queue)[position - 1]
        
        # Проверяем права
        is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
        is_requester = track['requester'].id == ctx.author.id
        
        if not (is_dj or is_requester):
            await self.send_embed(
                ctx,
                "❌ Ошибка",
                "Вы можете удалить только запрошенный вами трек или иметь роль DJ",
                COLORS['ERROR']
            )
            return False
        
        # Удаляем трек
        del self.queue[position - 1]
        
        await self.send_embed(
            ctx,
            "🗑️ Трек удален",
            f"Трек **{track['title']}** удален из очереди",
            COLORS['SUCCESS']
        )
        return True
    
    async def search_tracks(self, ctx, query, max_results=5):
        """Ищет треки и позволяет пользователю выбрать из результатов"""
        # Отправляем начальное сообщение
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
            
            # Создаем список для выбора
            description = "Выберите трек, отправив его номер:"
            fields = []
            
            for i, entry in enumerate(valid_entries, 1):
                title = entry.get('title', 'Unknown')
                uploader = entry.get('uploader', 'Unknown')
                duration = format_duration(entry.get('duration', 0))
                fields.append((
                    f"{i}. {title}", 
                    f"От: {uploader} | Длительность: {duration}",
                    False
                ))
            
            await loading_message.edit(
                embed=create_embed(
                    f"🔍 Результаты поиска '{query}'",
                    description,
                    fields=fields,
                    footer=f"Введите номер (1-{len(valid_entries)}) или 'отмена'"
                )
            )
            
            # Ожидаем ответ
            def check_response(m):
                if m.author != ctx.author or m.channel != ctx.channel:
                    return False
                if m.content.lower() in ['отмена', 'cancel']:
                    return True
                return m.content.isdigit() and 1 <= int(m.content) <= len(valid_entries)
            
            try:
                response = await self.bot.wait_for('message', check=check_response, timeout=30)
                
                # Отмена
                if response.content.lower() in ['отмена', 'cancel']:
                    await self.send_embed(ctx, "🚫 Отменено", "Поиск отменен", COLORS['DEFAULT'])
                    return
                
                # Получаем выбранный трек
                choice = int(response.content)
                selected = valid_entries[choice - 1]
                
                # Ищем URL
                url = selected.get('url', selected.get('webpage_url'))
                if not url:
                    await self.send_embed(
                        ctx, 
                        "❌ Ошибка", 
                        "Не удалось получить URL для выбранного трека", 
                        COLORS['ERROR']
                    )
                    return
                
                # Добавляем трек
                await self.add_track(ctx, url)
                
            except asyncio.TimeoutError:
                await self.send_embed(ctx, "⏱️ Время истекло", "Вы не выбрали трек вовремя", COLORS['ERROR'])
                
        except Exception as e:
            logger.error(f"Ошибка при поиске: {e}", exc_info=True)
            await loading_message.edit(
                embed=create_embed("❌ Ошибка", f"Ошибка при поиске: {str(e)[:900]}", COLORS['ERROR'])
            )


# Экспортируемые функции для внешнего использования
async def ensure_voice(ctx):
    """Проверяет и обеспечивает голосовое подключение"""
    if not ctx.author.voice:
        await ctx.send(
            embed=create_embed("❌ Ошибка", "Вы должны быть в голосовом канале", COLORS['ERROR'])
        )
        return False
    
    # Подключаемся или перемещаемся
    voice_client = ctx.guild.voice_client
    if not voice_client:
        await ctx.author.voice.channel.connect()
    elif voice_client.channel != ctx.author.voice.channel:
        await voice_client.move_to(ctx.author.voice.channel)
    
    return True

async def handle_play(ctx, query):
    """Обрабатывает команду воспроизведения"""
    if not query:
        await ctx.send(
            embed=create_embed("❌ Ошибка", "Укажите запрос или ссылку для воспроизведения", COLORS['ERROR'])
        )
        return
    
    # Проверяем голосовое подключение
    if not await ensure_voice(ctx):
        return
    
    # Получаем плеер
    player = get_player(ctx.bot)
    
    # URL или поиск
    if query.startswith(('http://', 'https://')):
        await player.add_track(ctx, query)
    else:
        await player.search_tracks(ctx, query)

async def handle_skip(ctx):
    """Обрабатывает команду пропуска трека"""
    player = get_player(ctx.bot)
    await player.skip_track(ctx)

async def handle_stop(ctx):
    """Обрабатывает команду остановки воспроизведения"""
    player = get_player(ctx.bot)
    await player.stop_playback(ctx)

async def handle_pause(ctx):
    """Обрабатывает команду паузы"""
    player = get_player(ctx.bot)
    await player.pause_resume(ctx, pause=True)

async def handle_resume(ctx):
    """Обрабатывает команду возобновления"""
    player = get_player(ctx.bot)
    await player.pause_

async def handle_remove(ctx, position):
    """Обрабатывает команду удаления трека из очереди"""
    player = get_player(ctx.bot)
    await player.remove_from_queue(ctx, position)

async def cleanup_player(guild):
    """Очищает состояние плеера после отключения бота"""
    player = get_player(None)  # Только получение существующего плеера
    
    # Очищаем состояние
    player.queue.clear()
    player.current = None
    
    # Удаляем сообщение "сейчас играет"
    if player.now_playing_message:
        try:
            await player.now_playing_message.delete()
        except:
            pass
        player.now_playing_message = None
    
    logger.info(f"Плеер очищен для гильдии {guild.name}")

async def auto_disconnect(guild, voice_channel):
    """Автоматически отключает бота, когда все пользователи вышли из канала"""
    player = get_player(None)  # Только получение существующего плеера
    
    # Отправляем сообщение
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
    
    # Отключаемся
    try:
        if guild.voice_client:
            await guild.voice_client.disconnect()
    except Exception as e:
        logger.error(f"Ошибка при отключении от голосового канала: {e}")
    
    # Очищаем состояние
    await cleanup_player(guild)
    
    logger.info(f"Бот автоматически отключен от канала {voice_channel.name}")