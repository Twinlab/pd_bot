# avatar.py
import discord

async def handle_avatar(ctx, mentioned_user: discord.Member = None):
    if not mentioned_user:
        mentioned_user = ctx.author

    server_avatar = mentioned_user.display_avatar.url
    global_avatar = mentioned_user.avatar.url

    embed = discord.Embed(title=f"{mentioned_user.name}'s avatar", color=discord.Color.blue())
    embed.set_image(url=server_avatar)
    embed.description = (
        f"[Server Avatar]({server_avatar}) | "
        f"[Global Avatar]({global_avatar})"
    )

    await ctx.send(embed=embed)
