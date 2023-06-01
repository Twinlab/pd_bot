import requests
import json
import asyncio
import os
import aiohttp

TWITCH_USER_API_ENDPOINT = 'https://api.twitch.tv/helix/users?login={}'
TWITCH_STREAM_API_ENDPOINT = 'https://api.twitch.tv/helix/streams?user_id={}'
TWITCH_STREAMS_JSON = "twitch_streams.json"

with open("config.json", "r") as f:
    config = json.load(f)

if os.path.exists(TWITCH_STREAMS_JSON):
    with open(TWITCH_STREAMS_JSON, "r") as f:
        twitch_data = json.load(f)
else:
    twitch_data = {}

online_streamers = set()

class Twitch:
    def __init__(self):
        self.client_id = config["TWITCH_CLIENT_ID"]
        self.client_secret = config["TWITCH_CLIENT_SECRET"]
        self.oauth_token = self.get_app_access_token()
        self.headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.oauth_token}"
        }

    def get_app_access_token(self):
        url = 'https://id.twitch.tv/oauth2/token'
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        response = requests.post(url, params=params).json()
        if "access_token" in response:
            return response["access_token"]
        else:
            print(f"Unexpected response while getting app access token: {response}")
            return None
        
    async def get_user_info(self, streamer_name):
        url = f"https://api.twitch.tv/helix/users?login={streamer_name}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                user_info = await resp.json()
        return user_info

    def get_stream_by_name(self, streamer_name):
        response = requests.get(TWITCH_USER_API_ENDPOINT.format(streamer_name), headers=self.headers)
        try:
            user_data = response.json()
            if user_data["data"]:
                user_id = user_data["data"][0]["id"]
                stream_response = requests.get(TWITCH_STREAM_API_ENDPOINT.format(user_id), headers=self.headers)
                return stream_response.json()
        except json.JSONDecodeError:
            print(f"Failed to parse JSON from response: {response.text}")
            return None

twitch_api = Twitch()

from discord import Embed

async def post_stream_live_notification(bot, stream):
    user_info = await twitch_api.get_user_info(stream["data"][0]["user_name"])
    avatar_url = user_info['data'][0]['profile_image_url']

    # Select a Discord channel to post the notification to.
    channel = bot.get_channel(config["DISCORD_CHANNEL_ID"])

    # Create the embed message.
    embed = Embed(
        title=stream["data"][0]["title"],
        url=f"https://www.twitch.tv/{stream['data'][0]['user_name']}",
        color=0x9146ff
    )
    embed.add_field(name="Игра", value=stream["data"][0]["game_name"])
    embed.set_thumbnail(url=avatar_url)
    embed.set_author(name=stream["data"][0]["user_name"], icon_url=avatar_url)
    embed.set_image(url=stream["data"][0]["thumbnail_url"].format(width=640, height=360))

    # Post the message to the Discord channel.
    await channel.send(embed=embed)

async def handle_twitch(ctx, streamer_name):
    if streamer_name not in twitch_data:
        user_info = await twitch_api.get_user_info(streamer_name)
        if user_info and user_info['data']:
            stream = twitch_api.get_stream_by_name(streamer_name)
            if stream and stream["data"]:
                twitch_data[streamer_name] = stream["data"][0]
            else:
                twitch_data[streamer_name] = {'user_name': streamer_name}
            with open(TWITCH_STREAMS_JSON, "w") as f:
                json.dump(twitch_data, f, indent=4)
            await ctx.send(f"Добавила {streamer_name} в список.")
        else:
            await ctx.send("Нет такого стримера.")
    else:
        await ctx.send("Такой стример уже есть в списке.")


async def remove_stream(ctx, streamer_name):
    if streamer_name in twitch_data:
        del twitch_data[streamer_name]
        with open(TWITCH_STREAMS_JSON, "w") as f:
            json.dump(twitch_data, f, indent=4)
        await ctx.send(f"Удалила {streamer_name} из списка.")
    else:
        await ctx.send("Нет такого стримера!")

async def check_streams(bot):
    while True:
        for streamer_name in twitch_data.keys():
            stream = twitch_api.get_stream_by_name(streamer_name)
            if stream and stream["data"]:
                # Streamer is online.
                if streamer_name not in online_streamers:
                    print(f"Streamer {streamer_name} has just gone online.")
                    online_streamers.add(streamer_name)
                    await post_stream_live_notification(bot, stream)
                else:
                    print(f"Streamer {streamer_name} is still online.")
            else:
                # Streamer is offline.
                if streamer_name in online_streamers:
                    print(f"Streamer {streamer_name} has just gone offline.")
                    online_streamers.remove(streamer_name)
                else:
                    print(f"Streamer {streamer_name} is still offline.")
        await asyncio.sleep(60)  # Check every minute.



