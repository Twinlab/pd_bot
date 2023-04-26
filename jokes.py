import random
import discord

async def handle_penis(ctx):
    user = ctx.author
    penis_length = random.randint(0, 15)
    penis_representation = "8" + "=" * penis_length + "D"

    embed = discord.Embed(title="Вычисление размера пениса юзера", color=0x00ff00)
    embed.add_field(name=f"{user.display_name}'s penis", value=penis_representation, inline=False)
    await ctx.send(embed=embed)