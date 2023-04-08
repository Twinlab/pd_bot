import discord
from discord.ext import commands
from on_message import handle_message
from snipe import on_message_delete as handle_message_delete, handle_snipe
from dota2 import handle_link, handle_lastmatch, save_user_links, user_links_file
import json
import os
from discord import Intents

with open("config.json", "r") as f:
    config = json.load(f)

intents = Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

user_links = {}

def load_user_links():
    global user_links
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

    user_links = user_links_dict


@bot.event
async def on_ready():
    load_user_links()
    print(f"Logged in as {bot.user.name}")
    print(user_links)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await handle_message(message)
    await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    await handle_message_delete(message)

@bot.command()
async def snipe(ctx):
    await handle_snipe(ctx)

@bot.command()
async def link(ctx, player_id: int):
    global user_links
    load_user_links()
    await handle_link(ctx, player_id, user_links)

@bot.command()
async def lastmatch(ctx, mentioned_user: discord.Member = None):
    await handle_lastmatch(ctx, user_links, mentioned_user)

bot.run(config["BOT_TOKEN"])
