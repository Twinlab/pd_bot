import discord
from discord.ext import commands
import asyncio

async def handle_giveaway(ctx, duration: str, *, description: str):
    embed = discord.Embed(title="Розыгрыш", description=description, color=discord.Color.green())
    embed.set_footer(text=f"Розыгрыш создан {ctx.author.name}", icon_url=ctx.author.avatar.url)
    giveaway_message = await ctx.send(embed=embed)
    await wait_and_collect_reactions(ctx, giveaway_message, duration)

async def wait_and_collect_reactions(ctx, giveaway_message, duration_str):
    duration = await parse_duration(duration_str)
    if duration is None:
        await ctx.send("Неверный формат времени. Используйте 's' для секунд, 'm' для минут и 'h' для часов. Например: 1h30m")
        return

    await asyncio.sleep(duration)
    message = await ctx.channel.fetch_message(giveaway_message.id)
    users = set()
    for reaction in message.reactions:
        async for user in reaction.users():
            if not user.bot:
                users.add(user.name)

    users_list = '\n'.join(users)
    await ctx.author.send(f"Список участников розыгрыша:\n{users_list}")

async def parse_duration(duration_str):
    seconds = 0
    duration_str = duration_str.lower()
    time_units = {'s': 1, 'm': 60, 'h': 3600}

    for unit, multiplier in time_units.items():
        if unit in duration_str:
            try:
                value = int(duration_str.split(unit)[0])
                seconds += value * multiplier
                duration_str = duration_str.split(unit)[1]
            except ValueError:
                return None
    return seconds if seconds > 0 else None