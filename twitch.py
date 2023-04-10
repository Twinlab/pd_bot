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

async def handle_twitch(ctx, stream_link, announcement_channel: discord.TextChannel = None):
    streams = load_twitch_streams()
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
            return len(data["data"]) > 0

async def twitch_checker(bot, twitch_client_id, twitch_client_secret):
    await bot.wait_until_ready()
    while not bot.is_closed():
        streams = load_twitch_streams()
        for stream in streams:
            live_status = await check_twitch_live_status(stream["url"], twitch_client_id, twitch_client_secret)
            if not stream["live"] and live_status:
                stream["live"] = True
                channel = bot.get_channel(stream["announcement_channel_id"])
                await channel.send(f"{stream['url']} подрубил!")
            elif stream["live"] and not live_status:
                stream["live"] = False
        with open(twitch_stream_file, "w") as f:
            json.dump(streams, f)
        await asyncio.sleep(60)



async def get_twitch_access_token(session, twitch_client_id, twitch_client_secret):
    url = f"https://id.twitch.tv/oauth2/token?client_id={twitch_client_id}&client_secret={twitch_client_secret}&grant_type=client_credentials"
    async with session.post(url) as response:
        data = await response.json()
        return data["access_token"]