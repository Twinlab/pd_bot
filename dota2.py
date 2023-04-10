import discord
import aiohttp
import json
import datetime

GAME_MODES = {
    0: "Unknown",
    1: "All Pick",
    2: "Captains Mode",
    3: "Random Draft",
    4: "Single Draft",
    5: "All Random",
    6: "Intro",
    7: "Diretide",
    8: "Reverse Captains Mode",
    9: "Greeviling",
    10: "Tutorial",
    11: "Mid Only",
    12: "Least Played",
    13: "Limited Heroes",
    14: "Compendium Matchmaking",
    15: "Custom",
    16: "Captains Draft",
    17: "Balanced Draft",
    18: "Ability Draft",
    19: "Event?",
    20: "All Random Death Match",
    21: "1v1 Mid",
    22: "All Draft",
    23: "Turbo",
    24: "Mutation",
    25: "Ranked All Pick"
}
user_links = {}
user_links_file = "user_links.json"
config_file = "config.json"

def save_user_links(user_links):
    with open(user_links_file, "w") as f:
        output_data = [{"user": user_id, "links": links} for user_id, links in user_links.items()]
        json.dump(output_data, f, ensure_ascii=False, indent=4)

        
async def fetch_hero_image_url(hero_id, heroes_data):
    hero_data = next((hero for hero in heroes_data if hero["id"] == hero_id), None)
    if not hero_data:
        return None

    hero_name = hero_data["name"].replace('npc_dota_hero_', '')
    hero_image_url = f"http://cdn.dota2.com/apps/dota2/images/heroes/{hero_name}_full.png"
    return hero_name, hero_image_url

async def fetch_heroes():
    global STEAM_API_KEY
    url = f"https://api.steampowered.com/IEconDOTA2_570/GetHeroes/v1?key={STEAM_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data["result"]["heroes"]

async def fetch_player_matches(player_id):
    url = f"https://api.opendota.com/api/players/{player_id}/matches?limit=1"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data
        
async def fetch_player_info(player_id):
    url = f"https://api.opendota.com/api/players/{player_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data
        
def load_config():
    with open(config_file, 'r') as f:
        config = json.load(f)
        return config.get('STEAM_API_KEY')

STEAM_API_KEY = load_config()

async def handle_link(ctx, player_id: int, user_links: dict):
    if ctx.author.id not in user_links:
        user_links[ctx.author.id] = []

    if player_id in user_links[ctx.author.id]:
        await ctx.send(f"Аккаунт Dota 2 с ID {player_id} уже привязан к аккаунту Discord <@{ctx.author.id}>.")
        return

    # Check if the player_id is already linked to another user
    for user_id, links in user_links.items():
        if player_id in links:
            await ctx.send(f"Аккаунт Dota 2 с ID {player_id} уже привязан к другому аккаунту Discord.")
            return

    user_links[ctx.author.id].append(player_id)
    save_user_links(user_links)
    await ctx.send(f"Аккаунт Dota 2 с ID {player_id} успешно привязан к аккаунту Discord <@{ctx.author.id}>.")

async def handle_unlink(ctx, user_links: dict, player_id=None):
    if player_id:
        if ctx.author.id in user_links and player_id in user_links[ctx.author.id]:
            user_links[ctx.author.id].remove(player_id)
            await ctx.send(f"Аккаунт Dota 2 с ID {player_id} успешно отвязан от аккаунта Discord <@{ctx.author.id}>.")
            save_user_links(user_links)
        else:
            await ctx.send(f"Аккаунт Dota 2 с ID {player_id} не был привязан к аккаунту Discord <@{ctx.author.id}>.")
    else:
        if ctx.author.id in user_links:
            del user_links[ctx.author.id]
            await ctx.send(f"Все аккаунты Dota 2 были успешно отвязаны от аккаунта Discord <@{ctx.author.id}>.")
            save_user_links(user_links)
        else:
            await ctx.send(f"Вы еще не привязали ни одного аккаунта Dota 2 к аккаунту Discord <@{ctx.author.id}>.")

async def handle_links(ctx, user_links):
    if ctx.author.id not in user_links:
        await ctx.send("Вы не привязывали аккаунт Dota 2 к своему аккаунту Discord. Используйте команду `!link PLAYER_ID`, чтобы привязать свой аккаунт.")
        return
    links = user_links[ctx.author.id]
    if not links:
        await ctx.send("Вы не привязали ни одного аккаунта Dota 2 к своему аккаунту Discord.")
        return
    message = "Ваши привязанные аккаунты Dota 2:\n"
    for link in links:
        message += f"{link}\n"
    await ctx.send(message)



async def handle_lastmatch(ctx, user_links: dict, mentioned_user: discord.Member = None):
    if mentioned_user:
        player_ids = user_links.get(mentioned_user.id, [])
        if not player_ids:
            await ctx.send(f"Пользователь {mentioned_user.mention} не привязал свой аккаунт Dota 2. Он должен использовать команду `!link PLAYER_ID`.")
            return
    else:
        player_ids = user_links.get(ctx.author.id, [])
        if not player_ids:
            await ctx.send("Сначала привяжите ваш аккаунт Discord к аккаунту Dota 2 с помощью команды `!link PLAYER_ID`.")
            return

    latest_match = None
    player_info = None
    for player_id in player_ids:
        matches = await fetch_player_matches(player_id)
        if not matches:
            continue

        last_match = matches[0]
        if not latest_match or last_match['start_time'] > latest_match['start_time']:
            latest_match = last_match
            player_info = await fetch_player_info(player_id)

    if not latest_match:
        await ctx.send("Не удалось получить информацию о последнем матче. Попробуйте позже.")
        return

    hero_id = latest_match["hero_id"]
    radiant_win = latest_match["radiant_win"]
    player_slot = latest_match["player_slot"]
    is_radiant = player_slot < 128
    result = "победил" if (radiant_win and is_radiant) or (not radiant_win and not is_radiant) else "проебал"
    kills = latest_match["kills"]
    deaths = latest_match["deaths"]
    assists = latest_match["assists"]
    heroes_data = await fetch_heroes()
    hero_name, hero_image_url = await fetch_hero_image_url(hero_id, heroes_data)

    match_url = f"https://www.dotabuff.com/matches/{latest_match['match_id']}"
    
    start_time = latest_match["start_time"]
    duration = latest_match["duration"]
    match_date = datetime.datetime.fromtimestamp(start_time)
    formatted_date = match_date.strftime("%d/%m/%Y")
    duration_string = f"{duration // 60}:{duration % 60}"
    game_mode_id = latest_match["game_mode"]
    game_mode = GAME_MODES.get(game_mode_id, "Неизвестный режим")

    kda_value = (kills + assists) / max(deaths, 1)

    if (radiant_win and is_radiant) or (not radiant_win and not is_radiant):
        kda_comment = "красава разъебал" if kda_value > 4 else "затащили дурака" if kda_value < 2 else "норм сыграл"
    else:
        kda_comment = "старался, команда подвела" if kda_value > 4 else "заруинил пидорас" if kda_value < 2 else "норм сыграл"

    stratz_url = f"https://stratz.com/matches/{latest_match['match_id']}"
    masked_match_id = f"{latest_match['match_id']}"
    player_name = player_info["profile"].get("personaname", "Неизвестный игрок")
    embed = discord.Embed(title=f"Match ID: {masked_match_id}", color=discord.Color.blue())
    embed.add_field(name="Имя аккаунта:", value=player_name, inline=True)
    embed.add_field(name="Результат:", value=result, inline=True)
    embed.add_field(name="KDA:", value=f"{kills}/{deaths}/{assists}", inline=True)
    embed.add_field(name="Мод игры:", value=game_mode, inline=True)
    embed.add_field(name="Дата:", value=formatted_date, inline=True)
    embed.add_field(name="Длительность:", value=duration_string, inline=True)

    if kda_comment:
        embed.add_field(name="Комментарий:", value=kda_comment, inline=False)

    embed.set_thumbnail(url=hero_image_url)

    embed.description = (
        f"[Dotabuff]({match_url}) | "
        f"[Stratz]({stratz_url})"
    )

    await ctx.send(embed=embed)


