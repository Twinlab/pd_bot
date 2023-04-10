import asyncio
import os
import subprocess
import discord
import yt_dlp
from discord.ext import commands


FFMPEG_OPTIONS = {
    'options': '-vn -c:a libmp3lame -q:a 4 -loglevel warning',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -protocol_whitelist "file,http,https,tcp,tls"'
}

ytdl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'quiet': True,
    'no_warnings': True,
    'verbose': True,
    'outtmpl': '/path/to/directory/%(id)s.%(ext)s',
}


class MusicPlayer:
    def __init__(self, ctx, bot):
        self.ctx = ctx
        self.bot = bot
        self.voice_client = ctx.voice_client

    async def play(self, url):
        try:
            async with self.ctx.typing():
                player = await YTDLSource.from_url(url, loop=self.bot.loop)
                self.voice_client.play(player, after=self._play_finished)

            embed = discord.Embed(
                title="Now playing",
                description=f"[{player.title}]({player.url})",
                color=discord.Color.green()
            )
            await self.ctx.send(embed=embed)

        except Exception as e:
            print(f'Error while playing audio: {e}')
            await self.ctx.send(f"Error while playing audio: {e}")

    def pause(self):
        self.voice_client.pause()
        self.ctx.send("Paused ⏸️")

    def resume(self):
        self.voice_client.resume()
        self.ctx.send("Resuming ⏯️")

    def stop(self):
        self.voice_client.stop()
        self.ctx.send("Stopped ⏹️")

    def skip(self):
        self.voice_client.stop()
        self.ctx.send("Skipped ⏭️")

    async def ensure_voice(self):
        if not self.voice_client or not self.voice_client.is_connected():
            if self.ctx.author.voice:
                channel = self.ctx.author.voice.channel
                self.voice_client = await channel.connect()
            else:
                await self.ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")
        elif self.voice_client.is_playing():
            self.voice_client.stop()

    async def disconnect(self):
        if self.voice_client:
            await self.voice_client.disconnect()

    def _play_finished(self, error):
        if error:
            print(f'Player error: {error}')
        coro = self.disconnect()
        fut = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f'Error while disconnecting from voice channel: {e}')


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()

        ytdl = yt_dlp.YoutubeDL(ytdl_opts)
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=True))

        if "entries" in data:
            data = data["entries"][0]

        print(f"Downloaded audio format: {data['format']} ({data['abr'] or 'unknown'} kbps)")

        filename = ytdl.prepare_filename(data)

        # Get the full path to the downloaded file
        filepath = os.path.abspath(filename)

        try:
            # Pass the full path to FFmpeg
            cmd = ['ffmpeg', '-i', filepath, *FFMPEG_OPTIONS['before_options'].split(), *FFMPEG_OPTIONS['options'].split()]
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                print(f"FFmpeg stdout: {stdout.decode('utf-8')}")
                print(f"FFmpeg stderr: {stderr.decode('utf-8')}")
                raise Exception("FFmpeg process returned a non-zero exit code")

            source = discord.FFmpegPCMAudio(executable="ffmpeg", source=filepath, **FFMPEG_OPTIONS)
        except Exception as e:
            print(f"FFmpeg error: {e}")
            return
        return cls(source, data=data)
    
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.command()
async def play(ctx, *, url):
    music_player = MusicPlayer(ctx, bot)
    await music_player.ensure_voice()
    await music_player.play(url)

@bot.command()
async def pause(ctx):
    music_player = MusicPlayer(ctx, bot)
    music_player.pause()

@bot.command()
async def resume(ctx):
    music_player = MusicPlayer(ctx, bot)
    music_player.resume()

@bot.command()
async def stop(ctx):
    music_player = MusicPlayer(ctx, bot)
    music_player.stop()

@bot.command()
async def skip(ctx):
    music_player = MusicPlayer(ctx, bot)
    music_player.skip()

@bot.command()
async def disconnect(ctx):
    music_player = MusicPlayer(ctx, bot)
    await music_player.disconnect()

bot.run('NjcxMTQxNDU5ODgxMDk5Mjc3.G0RWKU.SzgEXQ4F6TIYqZw0MN_Fim3uMk1_OGASV7fe7c')

