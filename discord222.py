import discord
import random
from discord.ext import commands
import asyncio

TOKEN = 'NjcxMTQxNDU5ODgxMDk5Mjc3.G0RWKU.SzgEXQ4F6TIYqZw0MN_Fim3uMk1_OGASV7fe7c'

intents = discord.Intents.default()
intents.messages = True
intents.reactions = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)
most_reacted_posts = {}

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

async def fetch_history(ctx):
    global most_reacted_posts

    most_reacted_posts = {}
    total_channels = len(ctx.guild.text_channels)
    progress_message = await ctx.send('Started fetching message history...')
    await ctx.send(f'Fetching message history: 0/{total_channels} channels processed')

    tasks = [fetch_message_history(channel) for channel in ctx.guild.text_channels]
    await asyncio.gather(*tasks)

    await ctx.send('Message history fetched and most reacted posts list updated.')

async def fetch_message_history(channel):
    global most_reacted_posts

    async for message in channel.history(limit=None):  # Установите параметр limit в None
        total_reactions = sum([react.count for react in message.reactions])

        if total_reactions > 0:
            most_reacted_posts[message.id] = {
                'total_reactions': total_reactions,
                'message': message
            }
    
@bot.event
async def on_message(message):
    if message.author.id == 154601435990982656 and random.random() < 0.05:
        await message.channel.send('иди нахуй абасранер')

    # Don't forget to process bot commands after checking the author's ID
    await bot.process_commands(message)
    
@bot.command(name='fetch_history', help='Fetches message history and updates most reacted posts list.')
@commands.has_permissions(administrator=True)
async def fetch_history(ctx):
    global most_reacted_posts

    most_reacted_posts = {}
    total_channels = len(ctx.guild.text_channels)
    progress_message = await ctx.send('Started fetching message history...')
    await ctx.send(f'Fetching message history: 0/{total_channels} channels processed')

    for index, channel in enumerate(ctx.guild.text_channels, start=1):
        await fetch_message_history(channel)
        await progress_message.edit(content=f'Fetching message history: {index}/{total_channels} channels processed')

    await ctx.send('Message history fetched and most reacted posts list updated.')

@fetch_history.error
async def fetch_history_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('You do not have permission to use this command.')


@bot.command(name='top_posts', help='Shows the top 20 most reacted posts in the current channel.')

async def top_posts(ctx):
    if ctx.channel.id not in most_reacted_posts:
        await ctx.send("No message history found for this channel. Run !fetch_history first.")
        return

    channel_posts = [post for post in most_reacted_posts.values() if post['message'].channel.id == ctx.channel.id]
    top_20_posts = sorted(channel_posts, key=lambda x: x['total_reactions'], reverse=True)[:20]
    response = 'Top 20 most reacted posts in this channel:\n'

    for index, post in enumerate(top_20_posts, start=1):
        response += f"{index}. {post['message'].jump_url} (Reactions: {post['total_reactions']})\n"

    await ctx.send(response)


@bot.command(name='hello', help='Greets the user.')
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.mention}!')

bot.run(TOKEN)