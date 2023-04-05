import discord
from discord.ext import commands, tasks
import json
import time
import asyncio

# Создайте файл "config.json" с токеном вашего бота и айди администратора
with open('config.json') as f:
    config = json.load(f)

TOKEN = config["token"]
ADMIN_ID = config["admin_id"]

intents = discord.Intents.default()
intents.messages = True
intents.reactions = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Обработка события запуска бота
@bot.event
async def on_ready():
    print(f"{bot.user.name} is ready!")

@bot.command(name="parse")
@commands.is_owner()
async def parse_messages(ctx):
    all_channels = ctx.guild.channels
    channels_to_parse = [channel for channel in all_channels if isinstance(channel, discord.TextChannel)]

    progress_message = await ctx.send("Процесс парсинга начался...\nПрогресс - 0%/100%")

    channels_parsed = 0
    reactions_data = {}
    update_interval = 10 * 60  # Обновление прогресса каждые 10 минут
    last_update_time = time.time()

    for channel in channels_to_parse:
        async for message in channel.history(limit=None):
            if message.reactions:
                unique_users = set()
                for reaction in message.reactions:
                    async for user in reaction.users():
                        unique_users.add(user.id)
                reactions_data[message.id] = {
                    "reactions": len(unique_users),
                    "author_id": message.author.id,
                    "channel_id": message.channel.id
                }
                with open("reactions_data.json", "w") as f:
                    json.dump(reactions_data, f)

        channels_parsed += 1

        if time.time() - last_update_time >= update_interval:
            progress = int(channels_parsed / len(channels_to_parse) * 100)
            await progress_message.edit(content=f"Процесс парсинга начался...\nПрогресс - {progress}%/100%")
            last_update_time = time.time()

    progress = int(channels_parsed / len(channels_to_parse) * 100)
    await progress_message.edit(content=f"Процесс парсинга начался...\nПрогресс - {progress}%/100%")
    await ctx.send("Парсинг завершен!")

@bot.command(name="top20")
async def show_top_20(ctx):
    with open("reactions_data.json") as f:
        reactions_data = json.load(f)

    sorted_data = sorted(reactions_data.items(), key=lambda x: x[1]["reactions"], reverse=True)[:20]

    top_posts = ""
    for i, (message_id, message_data) in enumerate(sorted_data, start=1):
        author = await bot.fetch_user(message_data["author_id"])
        channel = bot.get_channel(message_data["channel_id"])
        message_link = f"https://discord.com/channels/{ctx.guild.id}/{channel.id}/{message_id}"
        top_posts += f"{i}. [{author.name}]({message_link}) - {message_data['reactions']} reactions\n"

    embed = discord.Embed(title="Топ-20 постов по количеству реакций", description=top_posts, color=discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(name="hello")
async def test_command(ctx):
    await ctx.send("Hello!")

@parse_messages.error
async def parse_error(ctx, error):
    if isinstance(error, commands.errors.NotOwner):
        await ctx.send("пашол нах ты не админ")

bot.run(TOKEN)