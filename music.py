import asyncio
import functools
import yt_dlp
from discord.voice_client import VoiceClient
import discord
from discord.ext import commands
import time

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "extractaudio": True,
    "audioformat": "mp3",
    "outtmpl": "downloads/%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class Song:
    def __init__(self, url, data, requester):
        self.url = url
        self.title = data.get("title")
        self.uploader = data.get("uploader")
        self.requester = requester

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, functools.partial(ytdl.extract_info, url, download=not stream)
        )

        if "entries" in data:
            data = data["entries"][0]

        filename = data["url"] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)
    
queue = []

async def show_queue(ctx):
    if len(queue) == 0:
        await ctx.send("Очередь пуста")
    else:
        queue_list = "Текущая очередь:\n"
        for i, song in enumerate(queue):
            queue_list += f"{i+1}. {song.title} ({song.uploader}), заказал: {song.requester}\n"  # Изменено
        await ctx.send(queue_list)

async def skip_song(ctx):
    if not ctx.voice_client.is_playing():
        await ctx.send("Сейчас ничего не играет.")
        return

    if ctx.author.guild_permissions.administrator:
        if not queue:
            ctx.voice_client.stop()
            await ctx.send("Очередь пуста.")
        else:
            await play_next_song(ctx)
    else:
        message = await ctx.send("Голосование для пропуска песни началось. Для пропуска песни требуется больше половины голосов участников голосового канала.")
        await add_reactions(message)

        voice_channel_members = len(ctx.author.voice.channel.members) - 1
        required_votes = voice_channel_members // 2 + 1

        def check(reaction, user):
            return (
                user != ctx.bot.user
                and reaction.message.id == message.id
                and str(reaction.emoji) in ["✅", "❌"]
            )

        try:
            votes = {"✅": 0, "❌": 0}
            while True:
                reaction, _ = await ctx.bot.wait_for("reaction_add", timeout=60.0, check=check)
                if reaction.count > 1:
                    votes[str(reaction.emoji)] += 1

                if votes["✅"] >= required_votes:
                    if not queue:
                        ctx.voice_client.stop()
                        await ctx.send("Очередь пуста.")
                    else:
                        await play_next_song(ctx)
                        await ctx.send("Песня пропущена.")
                    break
                elif votes["❌"] >= required_votes:
                    await ctx.send("Голосование завершено. Песня не будет пропущена.")
                    break
        except asyncio.TimeoutError:
            await ctx.send("Время голосования истекло.")


async def join_channel(ctx, *, channel: discord.VoiceChannel):
    if ctx.voice_client is not None:
        return await ctx.voice_client.move_to(channel)

    await channel.connect()

async def add_reactions(message):
    await message.add_reaction("✅")
    await message.add_reaction("❌")

async def play_music(ctx, *, query):
    if ctx.author.voice is None:
        await ctx.send("сначала зайди в войс")
        return

    voice_channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        await voice_channel.connect()
    elif ctx.voice_client.channel != voice_channel:
        await ctx.send("Бот уже занят в другом канале")
        return

    async with ctx.typing():
        player = await YTDLSource.from_url(query, loop=ctx.bot.loop, stream=True)
        song = Song(query, player.data, ctx.author.display_name)

        if not ctx.voice_client.is_playing():
            ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next_song(ctx), ctx.bot.loop) if not e else None)
            ctx.current_requester = ctx.author
            await ctx.send(f"Сейчас играет: {song.title}, заказал {ctx.author.display_name}")
            await update_bot_status(ctx, song.title)
        else:
            queue.append(song)
            position = len(queue)
            await ctx.send(f"Добавлен в очередь: {song.title} (позиция: {position})")

async def update_bot_status(ctx, title):
    listening = discord.Activity(type=discord.ActivityType.listening, name=f"{title}")
    await ctx.bot.change_presence(status=discord.Status.online, activity=listening)

async def clear_bot_status(ctx):
    await ctx.bot.change_presence(activity=discord.Game(name="Делаю милые вещи и пью чай"))


async def leave_if_empty(ctx):
    while ctx.voice_client is not None and ctx.voice_client.is_connected():
        if len(ctx.voice_client.channel.members) == 1:  # Только бот в голосовом канале
            await asyncio.sleep(10)
            if ctx.voice_client is not None and len(ctx.voice_client.channel.members) == 1:  # Проверка после 10 секунд
                await ctx.voice_client.disconnect()
                break
        await asyncio.sleep(5)

async def auto_leave(ctx):
    while ctx.voice_client is not None and ctx.voice_client.is_connected():
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            await asyncio.sleep(5)
        elif len(queue) == 0:
            await asyncio.sleep(180)  # 3 минуты
            if not ctx.voice_client.is_playing() and len(queue) == 0:
                await ctx.voice_client.disconnect()
                break
        await leave_if_empty(ctx)

async def play_next_song(ctx):
    if len(queue) > 0:
        song = queue.pop(0)
        player = await YTDLSource.from_url(song.url, loop=ctx.bot.loop, stream=True)
        ctx.voice_client.stop()
        ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next_song(ctx), ctx.bot.loop) if not e else None)
        ctx.current_requester = song.requester
        await ctx.send(f"Следующий трек начинается: {song.title}, заказал {ctx.author.display_name}")
        await update_bot_status(ctx, song.title)  # Добавлено
    else:
        await ctx.send("Очередь пуста.")
        await clear_bot_status(ctx)  # Очищаем статус бота
        asyncio.create_task(auto_leave(ctx))

async def pause_music(ctx):
    ctx.voice_client.pause()
    await ctx.send("Запаузила")

async def resume_music(ctx):
    ctx.voice_client.resume()
    await ctx.send("Запускаю")

async def stop_music(ctx):
    ctx.voice_client.stop()
    await ctx.send("Стопнула")
    await clear_bot_status(ctx)

async def leave_channel(ctx):
    await ctx.voice_client.disconnect()
    await ctx.send("Всем пока, спасибо за прослушивание!")
    await clear_bot_status(ctx)  # Очищаем статус бота
