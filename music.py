import discord
import asyncio
import logging
import os
import math
from discord.ext import commands
import yt_dlp
from collections import deque

# Настройка логирования
logger = logging.getLogger("music")

# Улучшенные настройки для yt-dlp с лучшим качеством звука
ytdl_format_options = {
    # Приоритет форматов: opus в максимальном качестве > mp4a высокого качества > остальные
    'format': '251/250/249/140/bestaudio[acodec=opus]/bestaudio/best',
    'outtmpl': 'downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    # Увеличиваем качество аудио
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '192',
    }],
}

# Улучшенные настройки FFmpeg для лучшего качества звука
ffmpeg_options = {
    'options': '-vn -af "loudnorm=I=-16:LRA=11:TP=-1.5" -b:a 192k',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

# Создаем директорию для загрузок, если ее нет
if not os.path.exists('downloads'):
    os.makedirs('downloads')

# Цвета для эмбедов
EMBED_COLOR = 0x3498db  # Голубой
ERROR_COLOR = 0xe74c3c  # Красный
SUCCESS_COLOR = 0x2ecc71  # Зеленый

# Класс для музыкального плеера
class MusicPlayer:
    """Класс для управления воспроизведением музыки в гильдии"""
    def __init__(self, guild):
        self.guild = guild
        self.queue = deque()  # Очередь треков
        self.current = None  # Текущий трек
        self.volume = 0.5  # Громкость (0.0 - 1.0)
        self.skip_votes = set()  # Голоса за пропуск трека
        self.text_channel = None  # Текстовый канал для сообщений
        self.now_playing_message = None  # Сообщение "Сейчас играет"

    def clear_votes(self):
        """Очищает голоса за пропуск"""
        self.skip_votes.clear()

# Словарь музыкальных плееров
players = {}

def get_player(guild):
    """Получение или создание плеера для гильдии"""
    if guild.id in players:
        return players[guild.id]
    else:
        player = MusicPlayer(guild)
        players[guild.id] = player
        return player

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5, requester=None):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown title')
        self.url = data.get('webpage_url', data.get('url', None))
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail', None) 
        self.requester = requester  # Пользователь, запросивший трек
        self.uploader = data.get('uploader', 'Unknown uploader')
        self.uploader_url = data.get('uploader_url', None)
        self.id = data.get('id', '')

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop=None, stream=True, requester=None):
        loop = loop or asyncio.get_event_loop()
        
        # Создаем экземпляр yt-dlp с текущими настройками
        ytdl = yt_dlp.YoutubeDL(ytdl_format_options)
        
        # Обработка поисковых запросов
        if not (search.startswith('http://') or search.startswith('https://')):
            search = f"ytsearch:{search}"
        
        # Получаем информацию о видео
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=not stream))
        
        # Если это результат поиска, берем первый элемент
        if 'entries' in data:
            data = data['entries'][0]
        
        # Для потоковой передачи можно возвращать данные без создания аудио источника
        # Это позволит отложить создание аудио до момента воспроизведения
        return {'data': data, 'requester': requester}
    
    @classmethod
    async def create_audio_source(cls, data_dict, *, loop=None):
        """Создает аудио источник из данных трека"""
        loop = loop or asyncio.get_event_loop()
        data = data_dict['data']
        requester = data_dict['requester']
        
        # Находим лучший аудио формат
        audio_formats = [f for f in data['formats'] if f.get('acodec', 'none') != 'none']
        
        # Ищем предпочтительные форматы
        preferred_format_ids = ['251', '140', '250', '249']
        best_format = None
        
        for fmt_id in preferred_format_ids:
            for fmt in audio_formats:
                if fmt.get('format_id') == fmt_id:
                    best_format = fmt
                    break
            if best_format:
                break
        
        # Если предпочтительные форматы не найдены, берем лучший доступный
        if not best_format and audio_formats:
            for fmt in audio_formats:
                if 'abr' in fmt:  # audio bitrate
                    if not best_format or fmt['abr'] > best_format.get('abr', 0):
                        best_format = fmt
            
            # Если форматы без bitrate, берем первый
            if not best_format:
                best_format = audio_formats[0]
        
        if best_format:
            source = discord.FFmpegPCMAudio(best_format['url'], **ffmpeg_options)
            return cls(source, data=data, volume=0.5, requester=requester)
        else:
            raise Exception("Не удалось найти подходящий аудио формат")

    @staticmethod
    def format_duration(duration) -> str:
        """Форматирует продолжительность из секунд в MM:SS или HH:MM:SS"""
        if not duration:
            return "∞"  # Для стримов
        
        # Преобразуем в целое число на всякий случай
        try:
            duration = int(float(duration))
        except (ValueError, TypeError):
            return "?:??"  # Неизвестная продолжительность
        
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

# Функции для создания эмбедов
def create_now_playing_embed(track, guild):
    """Создает эмбед для текущего трека"""
    embed = discord.Embed(
        title=f"🎵 Сейчас играет",
        description=f"**[{track.title}]({track.url})**",
        color=EMBED_COLOR
    )
    
    # Добавляем тумбнейл, если доступен
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    
    # Информация о треке
    embed.add_field(name="Продолжительность", value=YTDLSource.format_duration(track.duration), inline=True)
    embed.add_field(name="Запросил", value=track.requester.mention if track.requester else "Unknown", inline=True)
    
    # Информация об авторе видео
    if track.uploader:
        uploader_text = f"[{track.uploader}]({track.uploader_url})" if track.uploader_url else track.uploader
        embed.add_field(name="Автор", value=uploader_text, inline=True)
    
    # Информация об очереди
    player = get_player(guild)
    if player.queue:
        next_track = player.queue[0].get('data', {}).get('title', 'Unknown')
        embed.add_field(
            name=f"Следующий трек (всего в очереди: {len(player.queue)})",
            value=f"**{next_track}**",
            inline=False
        )
    
    return embed

def create_queue_embed(guild, items_per_page=10):
    """Создает эмбед с очередью треков"""
    player = get_player(guild)
    
    if not player.queue and not player.current:
        embed = discord.Embed(
            title="Очередь пуста",
            description="Добавьте треки с помощью команды `!play` или `/play`",
            color=ERROR_COLOR
        )
        return embed
    
    # Упрощенный формат очереди
    embed = discord.Embed(
        title=f"🎵 Очередь воспроизведения",
        color=EMBED_COLOR
    )
    
    description = ""
    
    # Добавляем информацию о текущем треке
    if player.current:
        requester_mention = player.current.requester.mention if player.current.requester else "Unknown"
        description += f"**🔊 Сейчас играет:** [{player.current.title}]({player.current.url}) ({YTDLSource.format_duration(player.current.duration)}) - {requester_mention}\n\n"
    
    # Добавляем треки из очереди
    if player.queue:
        description += "**Следующие треки:**\n"
        for i, track_data in enumerate(player.queue, start=1):
            if i > items_per_page:  # Ограничиваем количество отображаемых треков
                remaining = len(player.queue) - items_per_page
                description += f"\n*...и еще {remaining} треков*"
                break
            
            track = track_data.get('data', {})
            requester = track_data.get('requester')
            title = track.get('title', 'Unknown')
            duration = YTDLSource.format_duration(track.get('duration', 0))
            url = track.get('webpage_url', track.get('url', '#'))
            requester_mention = requester.mention if requester else "Unknown"
            
            description += f"**{i}.** [{title}]({url}) ({duration}) - {requester_mention}\n"
    
    embed.description = description
    
    # Добавляем информацию о количестве треков
    total_tracks = len(player.queue) + (1 if player.current else 0)
    embed.set_footer(text=f"Всего треков: {total_tracks}")
    
    return embed

# Функции воспроизведения
async def play_next(guild):
    """Воспроизводит следующий трек из очереди"""
    player = get_player(guild)
    
    # Очищаем голоса за пропуск трека
    player.clear_votes()
    
    # Если очередь пуста, завершаем воспроизведение
    if not player.queue:
        # Удаляем сообщение "Сейчас играет" если оно есть
        if player.now_playing_message:
            try:
                await player.now_playing_message.delete()
                player.now_playing_message = None
            except discord.HTTPException:
                pass
                
        # Обнуляем текущий трек
        player.current = None
        
        # Отправляем сообщение о завершении очереди
        if player.text_channel:
            embed = discord.Embed(
                title="🎵 Очередь воспроизведения завершена",
                description="Очередь пуста. Добавьте треки с помощью команды `!play` или `/play`",
                color=EMBED_COLOR
            )
            await player.text_channel.send(embed=embed)
            
        return
    
    # Берем следующий трек из очереди
    track_data = player.queue.popleft()
    
    try:
        # Создаем аудио источник
        source = await YTDLSource.create_audio_source(track_data, loop=asyncio.get_event_loop())
        
        # Устанавливаем громкость
        source.volume = player.volume
        
        # Сохраняем текущий трек
        player.current = source
        
        # Начинаем воспроизведение
        guild.voice_client.play(source)
        
        # Отправляем сообщение "Сейчас играет"
        if player.text_channel:
            embed = create_now_playing_embed(source, guild)
            
            # Удаляем предыдущее сообщение
            if player.now_playing_message:
                try:
                    await player.now_playing_message.delete()
                except discord.HTTPException:
                    pass
            
            player.now_playing_message = await player.text_channel.send(embed=embed)
            
    except Exception as e:
        logger.error(f"Ошибка при воспроизведении следующего трека: {e}", exc_info=True)
        
        if player.text_channel:
            await player.text_channel.send(
                embed=discord.Embed(
                    title="❌ Ошибка воспроизведения",
                    description=f"Не удалось воспроизвести трек: {str(e)[:1000]}",
                    color=ERROR_COLOR
                )
            )
        
        # Пробуем воспроизвести следующий трек
        await play_next(guild)
# Основные функции для обработки команд
async def handle_play(ctx, query):
    """Обрабатывает команду воспроизведения с поиском"""
    try:
        # Проверяем, находится ли пользователь в голосовом канале
        if ctx.author.voice is None:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Вы должны быть в голосовом канале для воспроизведения музыки.",
                color=ERROR_COLOR
            )
            await ctx.send(embed=embed)
            return

        voice_channel = ctx.author.voice.channel
        
        # Получаем или создаем плеер
        player = get_player(ctx.guild)
        
        # Запоминаем текстовый канал
        player.text_channel = ctx.channel
        
        # Проверяем, подключен ли бот к голосовому каналу
        if ctx.voice_client is None:
            await voice_channel.connect()
        elif ctx.voice_client.channel != voice_channel:
            await ctx.voice_client.move_to(voice_channel)
        
        # Если это URL, сразу воспроизводим
        if query.startswith(('http://', 'https://')):
            await add_track_to_queue(ctx, query)
            return
        
        # Отправляем сообщение о поиске
        loading_message = await ctx.send(
            embed=discord.Embed(
                title="🔍 Поиск",
                description=f"Ищу `{query}` на YouTube...",
                color=EMBED_COLOR
            )
        )
        
        # Создаем настройки для поиска нескольких результатов
        search_opts = ytdl_format_options.copy()
        search_opts['default_search'] = 'ytsearch5'  # 5 результатов поиска
        search_opts['quiet'] = True
        search_opts['extract_flat'] = True  # Только базовая информация
        
        ytdl = yt_dlp.YoutubeDL(search_opts)
        
        # Выполняем поиск
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ytdl.extract_info(f"ytsearch5:{query}", download=False)
            )
            
            # Проверяем, что есть результаты
            if not info or not info.get('entries'):
                await loading_message.edit(
                    embed=discord.Embed(
                        title="❌ Ничего не найдено",
                        description=f"По запросу `{query}` ничего не найдено.",
                        color=ERROR_COLOR
                    )
                )
                return
        except Exception as e:
            logger.error(f"Ошибка при поиске: {e}", exc_info=True)
            await loading_message.edit(
                embed=discord.Embed(
                    title="❌ Ошибка поиска",
                    description=f"Произошла ошибка при поиске: {str(e)[:1000]}",
                    color=ERROR_COLOR
                )
            )
            return
        
        # Создаем сообщение с результатами
        embed = discord.Embed(
            title=f"🔍 Результаты поиска для '{query}'",
            description="Выберите трек, отправив его номер:",
            color=EMBED_COLOR
        )
        
        for i, entry in enumerate(info['entries'], start=1):
            if entry is None:  # Пропускаем недоступные результаты
                continue
                
            title = entry.get('title', 'Unknown title')
            uploader = entry.get('uploader', 'Unknown uploader')
            
            # Форматирование продолжительности с проверкой
            duration_value = entry.get('duration', 0)
            if duration_value is not None:
                duration = YTDLSource.format_duration(duration_value)
            else:
                duration = "∞"
            
            embed.add_field(
                name=f"{i}. {title}",
                value=f"От: {uploader} | Длительность: {duration}",
                inline=False
            )
        
        # Если нет результатов после фильтрации
        if len(embed.fields) == 0:
            await loading_message.edit(
                embed=discord.Embed(
                    title="❌ Ничего не найдено",
                    description=f"По запросу `{query}` не найдено доступных результатов.",
                    color=ERROR_COLOR
                )
            )
            return
        
        embed.set_footer(text="Введите номер трека для добавления в очередь (от 1 до 5) или 'отмена' для отмены.")
        
        await loading_message.edit(embed=embed)
        
        # Функция для проверки ответа
        def check(m):
            if m.author != ctx.author or m.channel != ctx.channel:
                return False
                
            if m.content.lower() in ['отмена', 'cancel']:
                return True
                
            if not m.content.isdigit():
                return False
                
            choice = int(m.content)
            valid_choices = [i for i, entry in enumerate(info['entries'], start=1) if entry is not None]
            return choice in valid_choices
        
        try:
            # Ожидаем ответ пользователя
            response = await ctx.bot.wait_for('message', check=check, timeout=30.0)
            
            # Если пользователь отменил
            if response.content.lower() in ['отмена', 'cancel']:
                await ctx.send(
                    embed=discord.Embed(
                        title="🚫 Поиск отменен",
                        description="Поиск был отменен.",
                        color=EMBED_COLOR
                    )
                )
                return
            
            # Получаем выбранный трек
            choice = int(response.content)
            selected_entry = None
            
            # Находим выбранный трек (с учетом возможных None значений)
            current_idx = 1
            for entry in info['entries']:
                if entry is not None:
                    if current_idx == choice:
                        selected_entry = entry
                        break
                    current_idx += 1
            
            if selected_entry is None:
                await ctx.send(
                    embed=discord.Embed(
                        title="❌ Ошибка выбора",
                        description="Не удалось найти выбранный трек. Попробуйте еще раз.",
                        color=ERROR_COLOR
                    )
                )
                return
            
            # Воспроизводим выбранный трек
            selected_url = selected_entry.get('url', selected_entry.get('webpage_url'))
            if not selected_url:
                await ctx.send(
                    embed=discord.Embed(
                        title="❌ Ошибка URL",
                        description="Не удалось получить URL для выбранного трека.",
                        color=ERROR_COLOR
                    )
                )
                return
                
            await add_track_to_queue(ctx, selected_url)
            
        except asyncio.TimeoutError:
            await ctx.send(
                embed=discord.Embed(
                    title="⏱️ Время вышло",
                    description="Вы не выбрали трек вовремя.",
                    color=ERROR_COLOR
                )
            )
    except Exception as e:
        logger.error(f"Ошибка при поиске/воспроизведении: {e}", exc_info=True)
        await ctx.send(
            embed=discord.Embed(
                title="❌ Ошибка",
                description=f"Произошла ошибка при поиске: {str(e)[:1000]}",
                color=ERROR_COLOR
            )
        )

async def add_track_to_queue(ctx, url):
    """Добавляет трек в очередь по URL"""
    try:
        # Отправляем сообщение о загрузке
        loading_message = await ctx.send(
            embed=discord.Embed(
                title="🔄 Загрузка трека",
                description=f"Загружаю информацию о треке...",
                color=EMBED_COLOR
            )
        )
        
        # Получаем информацию о треке
        track_data = await YTDLSource.create_source(ctx, url, requester=ctx.author)
        
        # Получаем плеер
        player = get_player(ctx.guild)
        
        # Добавляем трек в очередь
        player.queue.append(track_data)
        
        # Обновляем сообщение
        track_title = track_data['data'].get('title', 'Unknown')
        track_url = track_data['data'].get('webpage_url', track_data['data'].get('url', '#'))
        track_duration = YTDLSource.format_duration(track_data['data'].get('duration', 0))
        
        embed = discord.Embed(
            title="✅ Трек добавлен в очередь",
            description=f"**[{track_title}]({track_url})** ({track_duration})",
            color=SUCCESS_COLOR
        )
        
        # Добавляем информацию о позиции в очереди
        position = len(player.queue)
        if position > 1 or (position == 1 and ctx.voice_client.is_playing()):
            embed.set_footer(text=f"Позиция в очереди: {position}")
        
        await loading_message.edit(embed=embed)
        
        # Если бот не воспроизводит музыку, начинаем воспроизведение
        if not ctx.voice_client.is_playing():
            await play_next(ctx.guild)
    
    except Exception as e:
        logger.error(f"Ошибка при добавлении трека: {e}", exc_info=True)
        
        embed = discord.Embed(
            title="❌ Ошибка",
            description=f"Не удалось добавить трек: {str(e)[:1000]}",
            color=ERROR_COLOR
        )
        
        # Пытаемся обновить сообщение если оно существует, иначе отправляем новое
        try:
            if 'loading_message' in locals():
                await loading_message.edit(embed=embed)
            else:
                await ctx.send(embed=embed)
        except:
            await ctx.send(embed=embed)

async def handle_skip(ctx):
    """Обрабатывает команду пропуска трека"""
    player = get_player(ctx.guild)
    
    # Проверяем, есть ли активное воспроизведение
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        await ctx.send(
            embed=discord.Embed(
                title="❌ Ошибка",
                description="В данный момент ничего не воспроизводится.",
                color=ERROR_COLOR
            )
        )
        return
    
    # Проверяем, является ли пользователь диджеем или запросившим трек
    is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
    is_requester = player.current.requester == ctx.author if player.current else False
    
    # Если пользователь диджей или запросивший трек, пропускаем сразу
    if is_dj or is_requester:
        # Остановка текущего трека
        ctx.voice_client.stop()
        
        # Ручной переход к следующему треку
        await play_next(ctx.guild)
        
        await ctx.send(
            embed=discord.Embed(
                title="⏭️ Трек пропущен",
                description=f"Трек пропущен по запросу {ctx.author.mention}",
                color=SUCCESS_COLOR
            )
        )
        return
    
    # Получаем количество пользователей в канале (исключая бота)
    channel_members = len([m for m in ctx.voice_client.channel.members if not m.bot])
    
    # Минимальное количество голосов для пропуска (50% + 1)
    required_votes = math.ceil(channel_members / 2)
    
    # Если пользователь уже голосовал
    if ctx.author.id in player.skip_votes:
        await ctx.send(
            embed=discord.Embed(
                title="⏭️ Голосование за пропуск",
                description=f"Вы уже голосовали за пропуск!\nГолосов: {len(player.skip_votes)}/{required_votes}",
                color=EMBED_COLOR
            )
        )
        return
    
    # Добавляем голос
    player.skip_votes.add(ctx.author.id)
    
    # Проверяем количество голосов
    if len(player.skip_votes) >= required_votes:
        # Остановка текущего трека
        ctx.voice_client.stop()
        
        # Ручной переход к следующему треку
        await play_next(ctx.guild)
        
        await ctx.send(
            embed=discord.Embed(
                title="⏭️ Трек пропущен",
                description=f"Трек пропущен по результатам голосования ({len(player.skip_votes)}/{required_votes})",
                color=SUCCESS_COLOR
            )
        )
    else:
        # Показываем текущее количество голосов
        await ctx.send(
            embed=discord.Embed(
                title="⏭️ Голосование за пропуск",
                description=f"{ctx.author.mention} проголосовал за пропуск трека\nГолосов: {len(player.skip_votes)}/{required_votes}",
                color=EMBED_COLOR
            )
        )

async def handle_stop(ctx):
    """Останавливает воспроизведение и очищает очередь"""
    player = get_player(ctx.guild)
    
    if not ctx.voice_client:
        await ctx.send(
            embed=discord.Embed(
                title="❌ Ошибка",
                description="Я не нахожусь в голосовом канале.",
                color=ERROR_COLOR
            )
        )
        return
    
    # Очищаем очередь
    player.queue.clear()
    
    # Останавливаем воспроизведение
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
    
    # Отключаемся от голосового канала
    await ctx.voice_client.disconnect()
    
    # Удаляем сообщение "Сейчас играет" если оно есть
    if player.now_playing_message:
        try:
            await player.now_playing_message.delete()
            player.now_playing_message = None
        except:
            pass
    
    # Сбрасываем текущий трек
    player.current = None
    
    await ctx.send(
        embed=discord.Embed(
            title="⏹️ Воспроизведение остановлено",
            description="Очередь очищена, бот отключен от голосового канала.",
            color=SUCCESS_COLOR
        )
    )

async def handle_pause(ctx):
    """Ставит воспроизведение на паузу"""
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        await ctx.send(
            embed=discord.Embed(
                title="❌ Ошибка",
                description="В данный момент ничего не воспроизводится.",
                color=ERROR_COLOR
            )
        )
        return
    
    ctx.voice_client.pause()
    
    await ctx.send(
        embed=discord.Embed(
            title="⏸️ Пауза",
            description="Воспроизведение приостановлено.",
            color=EMBED_COLOR
        )
    )

async def handle_resume(ctx):
    """Возобновляет воспроизведение"""
    if not ctx.voice_client or not ctx.voice_client.is_paused():
        await ctx.send(
            embed=discord.Embed(
                title="❌ Ошибка",
                description="В данный момент ничего не приостановлено.",
                color=ERROR_COLOR
            )
        )
        return
    
    ctx.voice_client.resume()
    
    await ctx.send(
        embed=discord.Embed(
            title="▶️ Возобновление",
            description="Воспроизведение возобновлено.",
            color=SUCCESS_COLOR
        )
    )

async def handle_queue(ctx):
    """Показывает очередь воспроизведения"""
    player = get_player(ctx.guild)
    
    embed = create_queue_embed(ctx.guild)
    await ctx.send(embed=embed)
async def handle_remove(ctx, position: int):
    """Удаляет трек из очереди по позиции"""
    player = get_player(ctx.guild)
    
    # Проверяем, что позиция в допустимом диапазоне
    if position < 1 or position > len(player.queue):
        await ctx.send(
            embed=discord.Embed(
                title="❌ Ошибка",
                description=f"Позиция должна быть от 1 до {len(player.queue)}.",
                color=ERROR_COLOR
            )
        )
        return
    
    # Получаем трек по позиции
    queue_list = list(player.queue)
    track_data = queue_list[position - 1]
    track_title = track_data['data'].get('title', 'Unknown')
    
    # Проверяем, является ли пользователь запросившим трек или имеет роль DJ
    is_dj = any(role.name.lower() in ['dj', 'диджей'] for role in ctx.author.roles)
    is_requester = track_data.get('requester') == ctx.author
    
    if not (is_dj or is_requester):
        await ctx.send(
            embed=discord.Embed(
                title="❌ Ошибка",
                description="Вы можете удалить только запрошенные вами треки или иметь роль DJ.",
                color=ERROR_COLOR
            )
        )
        return
    
    # Удаляем трек
    del player.queue[position - 1]
    
    # Отправляем сообщение об успешном удалении
    await ctx.send(
        embed=discord.Embed(
            title="🗑️ Трек удален",
            description=f"Трек **{track_title}** удален из очереди.",
            color=SUCCESS_COLOR
        )
    )

async def cleanup_player(guild):
    """Очищает состояние плеера после отключения бота"""
    # Получаем плеер
    player = get_player(guild)
    
    # Очищаем очередь и сбрасываем текущий трек
    player.queue.clear()
    player.current = None
    
    # Удаляем сообщение "Сейчас играет" если оно есть
    if player.now_playing_message:
        try:
            await player.now_playing_message.delete()
            player.now_playing_message = None
        except:
            pass
            
    logger.info(f"Плеер очищен после отключения от голосового канала в гильдии {guild.name}")

async def auto_disconnect(guild, voice_channel):
    """Автоматически отключает бота, когда все пользователи вышли из канала"""
    # Получаем плеер
    player = get_player(guild)
    
    # Если есть текстовый канал, отправляем сообщение
    if player.text_channel:
        try:
            await player.text_channel.send(
                embed=discord.Embed(
                    title="👋 Автоматическое отключение",
                    description="Все пользователи покинули голосовой канал. Бот отключается.",
                    color=EMBED_COLOR
                )
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения об автоотключении: {e}")
    
    # Отключаем бота
    try:
        if guild.voice_client:
            await guild.voice_client.disconnect()
    except Exception as e:
        logger.error(f"Ошибка при отключении от голосового канала: {e}")
    
    # Очищаем состояние плеера
    await cleanup_player(guild)
    
    logger.info(f"Бот автоматически отключен от канала {voice_channel.name} в гильдии {guild.name}")