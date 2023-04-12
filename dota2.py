import discord
import aiohttp
import json
import datetime
import time

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
    if not isinstance(heroes_data, list):
        print("Warning: Invalid heroes_data format:", heroes_data)
        return None, None

    hero_data = next((hero for hero in heroes_data if hero["id"] == hero_id), None)

    if hero_data is None:
        print("Warning: Hero not found for hero_id:", hero_id)
        return None, None

    hero_image_url = f"http://cdn.dota2.com/apps/dota2/images/heroes/{hero_data['name'].replace('npc_dota_hero_', '')}_full.png"
    return hero_image_url

async def fetch_heroes():
    global STEAM_API_KEY
    url = f"https://api.steampowered.com/IEconDOTA2_570/GetHeroes/v1?key={STEAM_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data

async def fetch_player_matches(player_id):
    url = f"https://api.opendota.com/api/players/{player_id}/matches?limit=500"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return None
            data = await response.json()
            return data
        
async def fetch_player_info(player_id):
    url = f"https://api.opendota.com/api/players/{player_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data
        
def calculate_win_lose_stats(matches, player_id):
    now = time.time()
    daily_matches = [match for match in matches if (now - match['start_time']) <= 86400]
    weekly_matches = [match for match in matches if (now - match['start_time']) <= 604800]
    ranked_game_modes = {22, 25, 2}

    daily_wl = {'wins': 0, 'losses': 0}
    weekly_wl = {'wins': 0, 'losses': 0}

    for match in daily_matches:
        if match['game_mode'] in ranked_game_modes:
            is_radiant = match["player_slot"] < 128
            if (is_radiant and match["radiant_win"]) or (not is_radiant and not match["radiant_win"]):
                daily_wl['wins'] += 1
            else:
                daily_wl['losses'] += 1

    for match in weekly_matches:
        if match['game_mode'] in ranked_game_modes:
            is_radiant = match["player_slot"] < 128
            if (is_radiant and match["radiant_win"]) or (not is_radiant and not match["radiant_win"]):
                weekly_wl['wins'] += 1
            else:
                weekly_wl['losses'] += 1

    return daily_wl, weekly_wl

def get_player_role(player_slot):
    if 0 <= player_slot <= 4:
        return "Carry" if player_slot == 0 else "Mid" if player_slot == 1 else "Offlane" if player_slot == 2 else "Support" if player_slot == 3 else "Hard Support"
    elif 128 <= player_slot <= 132:
        return "Carry" if player_slot == 128 else "Mid" if player_slot == 129 else "Offlane" if player_slot == 130 else "Support" if player_slot == 131 else "Hard Support"
    else:
        return "Unknown"
    
def convert_average_rank_to_medal(average_rank):
    medals = {
        1: "Herald",
        2: "Guardian",
        3: "Crusader",
        4: "Archon",
        5: "Legend",
        6: "Ancient",
        7: "Divine",
        8: "Immortal",
    }

    medal_number = int(str(average_rank)[0])
    stars = int(str(average_rank)[1])

    if medal_number == 8:
        stars = 0

    return f"{medals[medal_number]} {stars}"
        
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
    hero_image_url = await fetch_hero_image_url(hero_id, heroes_data["result"]["heroes"])
    start_time = latest_match["start_time"]
    duration = latest_match["duration"]
    match_date = datetime.datetime.fromtimestamp(start_time)
    formatted_date = match_date.strftime("%d/%m/%Y")
    duration_string = f"{duration // 60}:{duration % 60}"
    #game_mode_id = latest_match["game_mode"]
    #game_mode = GAME_MODES.get(game_mode_id, "Неизвестный режим")
    match_history = await fetch_player_matches(player_id)
    #daily_wl, weekly_wl = calculate_win_lose_stats(match_history, player_id)
    player_role = get_player_role(player_slot)
    #daily_wl_str = f"{daily_wl['wins']}-{daily_wl['losses']}"
    #weekly_wl_str = f"{weekly_wl['wins']}-{weekly_wl['losses']}"
    average_rank = latest_match["average_rank"]
    rank = convert_average_rank_to_medal(average_rank)

    kda_value = (kills + assists) / max(deaths, 1)

    if (radiant_win and is_radiant) or (not radiant_win and not is_radiant):
        kda_comment = "красава разъебал" if kda_value > 4 else "затащили дурака" if kda_value < 2 else "норм сыграл"
    else:
        kda_comment = "старался, команда подвела" if kda_value > 4 else "заруинил пидорас" if kda_value < 2 else "норм сыграл"
        
    match_url = f"https://www.dotabuff.com/matches/{latest_match['match_id']}"
    stratz_url = f"https://stratz.com/matches/{latest_match['match_id']}"
    opendota_url = f"https://opendota.com/matches/{latest_match['match_id']}"
    masked_match_id = f"{latest_match['match_id']}"
    player_name = player_info["profile"].get("personaname", "Неизвестный игрок")

    embed = discord.Embed(title=f"Match ID: {masked_match_id}", color=discord.Color.blue())
    embed.add_field(name="Никнейм:", value=player_name, inline=True)
    embed.add_field(name="Результат:", value=result, inline=True)
    embed.add_field(name="KDA:", value=f"{kills}/{deaths}/{assists}", inline=True)
    embed.add_field(name="Аверага:", value=f"{rank}", inline=True)
    embed.add_field(name="Дата:", value=formatted_date, inline=True)
    embed.add_field(name="Длительность:", value=duration_string, inline=True)
    #embed.add_field(name="Роль:", value=player_role, inline=True)
    #embed.add_field(name="Ranked Daily W-L:", value=daily_wl_str, inline=True)
    #embed.add_field(name="Ranked Weekly W-L:", value=weekly_wl_str, inline=True)

    if kda_comment:
        embed.add_field(name="Комментарий:", value=kda_comment, inline=False)

    embed.set_thumbnail(url=hero_image_url)

    embed.description = (
        f"[Dotabuff]({match_url}) | "
        f"[Opendota]({opendota_url}) | "
        f"[Stratz]({stratz_url})"
    )

    await ctx.send(embed=embed)