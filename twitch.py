import aiohttp
import asyncio
import discord
import json
import os

twitch_stream_file = "twitch_streams.json"


def load_twitch_streams():
    if not os.path.exists(twitch_stream_file):
        with open(twitch_stream_file, "w") as f:
            json.dump([], f)

    with open(twitch_stream_file, "r") as f:
        try:
            loaded_data = json.load(f)
        except json.JSONDecodeError:
            loaded_data = []

    return loaded_data

async def handle_twitch(ctx, streamer, announcement_channel: discord.TextChannel = None):
    streams = load_twitch_streams()

    # Check if the input is a URL or just the streamer's name
    if streamer.startswith("http"):
        stream_link = streamer
    else:
        stream_link = f"https://www.twitch.tv/{streamer}"

    # Check if the stream already exists
    if any(stream["url"].lower() == stream_link.lower() for stream in streams):
        await ctx.send(f"Стрим {stream_link} уже существует.")
        return

    stream_data = {
        "url": stream_link,
        "channel_id": ctx.channel.id,
        "announcement_channel_id": announcement_channel.id if announcement_channel else ctx.channel.id,
        "live": False
    }
    streams.append(stream_data)
    with open(twitch_stream_file, "w") as f:
        json.dump(streams, f)
    await ctx.send(f"Добавила в список: {stream_link}")


async def check_twitch_live_status(stream_url, twitch_client_id, twitch_client_secret):
    async with aiohttp.ClientSession() as session:
        access_token = await get_twitch_access_token(session, twitch_client_id, twitch_client_secret)
        headers = {
            "Client-ID": twitch_client_id,
            "Authorization": f"Bearer {access_token}"
        }
        user_login = stream_url.split('/')[-1]
        url = f"https://api.twitch.tv/helix/streams?user_login={user_login}"
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            return len(data.get("data", [])) > 0

async def twitch_checker(bot, twitch_client_id, twitch_client_secret):
    await bot.wait_until_ready()
    
    # Check for active streams when the bot starts
    streams = load_twitch_streams()
    async with aiohttp.ClientSession() as session:
        access_token = await get_twitch_access_token(session, twitch_client_id, twitch_client_secret)
        for stream in streams:
            user_data, stream_data, game_data = await get_stream_info(session, stream["url"], twitch_client_id, access_token)
            live_status = len(stream_data.get("data", [])) > 0
            if live_status:
                stream["live"] = True
                channel = bot.get_channel(stream["announcement_channel_id"])
                await send_stream_embed(channel, user_data, stream_data, game_data, stream)
                
    # Check for live streams regularly
    while not bot.is_closed():
        streams = load_twitch_streams()
        async with aiohttp.ClientSession() as session:
            access_token = await get_twitch_access_token(session, twitch_client_id, twitch_client_secret)
            for stream in streams:
                user_data, stream_data, game_data = await get_stream_info(session, stream["url"], twitch_client_id, access_token)
                live_status = len(stream_data.get("data", [])) > 0
                if not stream["live"] and live_status:
                    stream["live"] = True
                    channel = bot.get_channel(stream["announcement_channel_id"])
                    user = user_data["data"][0]
                    stream_info = stream_data["data"][0]
                    game_name = game_data["data"][0]["name"] if game_data else "Неизвестная игра"
                    embed = discord.Embed(
                        title=stream_info["title"],
                        url=stream["url"],
                        description=f"**Игра:** {game_name}",
                        color=discord.Color.blue()
                    )
                    embed.set_author(name=user['display_name'], url=stream["url"], icon_url=user["profile_image_url"])
                    embed.set_thumbnail(url=user["profile_image_url"])
                    embed.set_image(url=stream_info["thumbnail_url"].format(width=640, height=360))
                    await channel.send(embed=embed)
                elif stream["live"] and not live_status:
                    stream["live"] = False
        with open(twitch_stream_file, "w") as f:
            json.dump(streams, f)
        await asyncio.sleep(60)

async def send_stream_embed(channel, user_data, stream_data, game_data, stream):
    user = user_data["data"][0]
    stream_info = stream_data["data"][0]
    game_name = game_data["data"][0]["name"] if game_data else "Неизвестная игра"
    embed = discord.Embed(
        title=stream_info["title"],
        url=stream["url"],
        description=f"**Игра:** {game_name}",
        color=discord.Color.blue()
    )
    embed.set_author(name=user['display_name'], url=stream["url"], icon_url=user["profile_image_url"])
    embed.set_image(url=stream_info["thumbnail_url"].format(width=640, height=360))
    await channel.send(embed=embed)

async def remove_stream(ctx, streamer_name):
    streams = load_twitch_streams()
    removed = False
    for i, stream in enumerate(streams):
        if stream['url'].lower().endswith(streamer_name.lower()):
            removed = True
            del streams[i]
            break

    if removed:
        with open(twitch_stream_file, "w") as f:
            json.dump(streams, f)
        await ctx.send(f"Удалила стрим {streamer_name}.")
    else:
        await ctx.send(f"Не нашла стрим {streamer_name}.")

async def get_stream_info(session, stream_url, twitch_client_id, access_token):
    headers = {
        "Client-ID": twitch_client_id,
        "Authorization": f"Bearer {access_token}"
    }
    user_login = stream_url.split('/')[-1]
    user_info_url = f"https://api.twitch.tv/helix/users?login={user_login}"
    stream_info_url = f"https://api.twitch.tv/helix/streams?user_login={user_login}"
    
    async with session.get(user_info_url, headers=headers) as user_response:
        user_data = await user_response.json()
    
    async with session.get(stream_info_url, headers=headers) as stream_response:
        stream_data = await stream_response.json()
    
    if stream_data.get("data"):
        game_id = stream_data["data"][0]["game_id"]
        game_info_url = f"https://api.twitch.tv/helix/games?id={game_id}"
        async with session.get(game_info_url, headers=headers) as game_response:
            game_data = await game_response.json()
    else:
        game_data = None

    return user_data, stream_data, game_data


async def get_twitch_access_token(session, twitch_client_id, twitch_client_secret):
    url = f"https://id.twitch.tv/oauth2/token?client_id={twitch_client_id}&client_secret={twitch_client_secret}&grant_type=client_credentials"
    async with session.post(url) as response:
        data = await response.json()
        return data["access_token"]