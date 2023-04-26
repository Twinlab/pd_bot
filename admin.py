import discord
from discord.ext import commands

async def clear_messages(ctx, count: int = 10, user: discord.Member = None):
    def check(msg):
        if user is None:
            return True
        else:
            return msg.author == user

    deleted = await ctx.channel.purge(limit=count, check=check, bulk=True)
    await ctx.send(f"Удалено {len(deleted)} сообщений.", delete_after=5)