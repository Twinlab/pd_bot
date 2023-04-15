import asyncio
import discord
import json
import os
from discord import Intents
from discord.ext import commands
from discord import app_commands
from on_message import handle_message
from snipe import on_message_delete as handle_message_delete, handle_snipe
from dota2 import handle_link, handle_unlink, handle_links, handle_lastmatch, save_user_links, user_links_file
from avatar import handle_avatar
from music import join_channel, play_music, pause_music, resume_music, stop_music, leave_channel, skip_song, show_queue, auto_leave
from twitch import load_twitch_streams, twitch_checker, handle_twitch
from giveaway import handle_giveaway

with open("config.json", "r") as f:
    config = json.load(f)

intents = Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

user_links = {}

def load_user_links():
    if not os.path.exists(user_links_file):
        with open(user_links_file, "w") as f:
            json.dump([], f)

    with open(user_links_file, "r") as f:
        try:
            loaded_data = json.load(f)
        except json.JSONDecodeError:
            loaded_data = []

    user_links_dict = {}
    for item in loaded_data:
        user_links_dict[item["user"]] = item["links"]

    return user_links_dict

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await handle_message(message)
    await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    await handle_message_delete(message)

@bot.hybrid_command()
async def snipe(ctx):
    await handle_snipe(ctx)

@bot.hybrid_command()
async def avatar(ctx, mentioned_user: discord.Member = None):
    await handle_avatar(ctx, mentioned_user)

@bot.hybrid_command()
async def link(ctx, player_id: int):
    user_links = load_user_links()
    await handle_link(ctx, player_id, user_links)

@bot.hybrid_command()
async def unlink(ctx, player_id: int = None):
    user_links = load_user_links()
    await handle_unlink(ctx, user_links, player_id)

@bot.hybrid_command()
async def links(ctx):
    user_links = load_user_links()
    await handle_links(ctx, user_links)

@bot.hybrid_command()
async def lastmatch(ctx, mentioned_user: discord.Member = None):
    user_links = load_user_links()
    await ctx.defer()
    await handle_lastmatch(ctx, user_links, mentioned_user)

@bot.hybrid_command()
async def join(ctx, *, channel: discord.VoiceChannel = None):
    if channel is None:
        channel = ctx.author.voice.channel
    await join_channel(ctx, channel=channel)

@bot.hybrid_command()
async def play(ctx, *, query):
    await play_music(ctx, query=query)
    await auto_leave(ctx)

@bot.hybrid_command()
async def pause(ctx):
    await pause_music(ctx)

@bot.hybrid_command()
async def resume(ctx):
    await resume_music(ctx)

@bot.hybrid_command()
async def stop(ctx):
    await stop_music(ctx)

@bot.hybrid_command()
async def leave(ctx):
    await leave_channel(ctx)

@bot.hybrid_command()
async def queue(ctx):
    await show_queue(ctx)

@bot.hybrid_command()
async def skip(ctx):
    await skip_song(ctx)

@bot.hybrid_command()
async def twitch(ctx, stream_link: str, announcement_channel: discord.TextChannel = None):
    await handle_twitch(ctx, stream_link, announcement_channel)

@bot.hybrid_command()
async def giveaway(ctx, duration: str, *, description: str):
    await handle_giveaway(ctx, duration, description=description)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    await bot.tree.sync()
    await bot.change_presence(activity=discord.Game(name="Делаю милые вещи и пью чай"))
    bot.loop.create_task(twitch_checker(bot, config["TWITCH_CLIENT_ID"], config["TWITCH_CLIENT_SECRET"])) 

if __name__ == "__main__":
    bot.run(config["BOT_TOKEN"])
