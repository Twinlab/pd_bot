import discord
import json
import requests
from datetime import datetime

# Function to read JSON data from a file
def read_json_file(file_name):
    with open(file_name) as f:
        return json.load(f)

# Function to make a GraphQL query to an API
def query_api(query, url, headers, variables=None):
    response = requests.post(url, json={'query': query, 'variables': variables}, headers=headers)
    return response.json()['data']

# Function to convert a player's position to a role
def get_role(player_role):
    roles = {
        'POSITION_1': 'Carry',
        'POSITION_2': 'Mid',
        'POSITION_3': 'Offlane',
        'POSITION_4': 'Soft Support',
        'POSITION_5': 'Hard Support'
    }
    return roles.get(player_role, 'Unknown')

# Function to convert an average rank to a medal
def convert_average_rank_to_medal(average_rank):
    if average_rank == 0:
      return 'Unknown'
    
    medals = ['Herald', 'Guardian', 'Crusader', 'Archon', 'Legend', 'Ancient', 'Divine', 'Immortal']
    roman_numerals = ['', 'I', 'II', 'III', 'IV', 'V']
    medal_number = int(str(average_rank)[0])
    stars_number = int(str(average_rank)[1])
    roman_stars = roman_numerals[stars_number]
    if medal_number == 8:  # Immortals doesn't have stars
        return f'{medals[medal_number]}'
    else:
        return f'{medals[medal_number]} {roman_stars}'
    
# Function to calculate daily and weekly win rates
def get_win_rates(player_matches, days=7):
    now = datetime.utcnow()
    daily_wins = [0] * days
    daily_losses = [0] * days
    weekly_wins = 0
    weekly_losses = 0

    for match in player_matches:
        match_time = datetime.utcfromtimestamp(match['startDateTime'])
        delta_days = (now - match_time).days

        if delta_days < days:
            is_victory = match['players'][0]['isVictory']
            if is_victory:
                daily_wins[delta_days] += 1
                weekly_wins += 1
            else:
                daily_losses[delta_days] += 1
                weekly_losses += 1

    return daily_wins, daily_losses, weekly_wins, weekly_losses

config = read_json_file('config.json')
user_links = read_json_file('user_links.json')

url = 'https://api.stratz.com/graphql'
headers = {'Authorization': f'Bearer {config["STRATZ_API_KEY"]}'}

async def handle_lastmatch(ctx, user_links: dict, member: discord.Member = None):
    if member:
        player_ids = user_links.get(member.id, [])
        if not player_ids:
            await ctx.send(f"Пользователь {member.mention} не привязал свой аккаунт Dota 2. Он должен использовать команду `!link PLAYER_ID`.")
            return
    else:
        player_ids = user_links.get(ctx.author.id, [])
        if not player_ids:
            await ctx.send("Сначала привяжите ваш аккаунт Discord к аккаунту Dota 2 с помощью команды `!link PLAYER_ID`.")
            return

    latest_match = {'id': None, 'startDateTime': 0}

    for player_id in player_ids:
      query_matches = '''
    query ($player_id: Long!) {
      player(steamAccountId: $player_id) {
        matches(request: {take: 1}) {
          id
          startDateTime
        }
      }
    }
    '''
      response = query_api(query_matches, url, headers, {'player_id': player_id})
      matches = response['player']['matches']
    
      if not matches:  # Если список матчей пуст, пропускаем текущую итерацию
        continue

      match = matches[0]
      if match['startDateTime'] > latest_match['startDateTime']:
        latest_match = match
        latest_player_id = player_id

# Добавьте проверку на наличие последнего матча
    if latest_match['id'] is None:
      await ctx.send("Не найдено ни одного доступного матча, скорее всего нужно включить доступность истории матчей в клиенте игры.")
      return

    query_match = '''
    query ($player_id: Long!, $match_id: Long!) {
      match(id: $match_id) {
        startDateTime
        durationSeconds
        rank
        players(steamAccountId: $player_id) {
          steamAccount {
            name
          }
          hero {
            shortName
      }
      position
      kills
      deaths
      assists
      isVictory
    }
  }
}
'''
    match_data = query_api(query_match, url, headers, {'player_id': latest_player_id, 'match_id': latest_match['id']})
    player_data = match_data['match']['players'][0]
    match_date = datetime.utcfromtimestamp(match_data['match']['startDateTime']).strftime('%d/%m/%Y')
    duration = match_data['match']['durationSeconds']
    actual_duration = f'{duration // 60}:{duration % 60:02}'
    match_result = 'победил' if player_data['isVictory'] else 'проебал'
    kda = f"{player_data['kills']}/{player_data['deaths']}/{player_data['assists']}"
    kda_value = (player_data['kills'] + player_data['assists']) / max(player_data['deaths'], 1)
    hero_name = player_data['hero']['shortName']
    hero_image_url = f'https://cdn.stratz.com/images/dota2/heroes/{hero_name}_horz.png'

    if (player_data['isVictory']):
        kda_comment = "красава разъебал" if kda_value > 4 else "затащили дурака" if kda_value < 2 else "норм сыграл"
    else:
        kda_comment = "старался, команда подвела" if kda_value > 4 else "заруинил пидорас" if kda_value < 2 else "норм сыграл"
        
    match_url = f"https://www.dotabuff.com/matches/{latest_match['id']}"
    stratz_url = f"https://stratz.com/matches/{latest_match['id']}"
    opendota_url = f"https://opendota.com/matches/{latest_match['id']}"
    masked_match_id = f"{latest_match['id']}"

    # Add this code after getting the latest match
    query_matches_week = '''
    query ($player_id: Long!) {
      player(steamAccountId: $player_id) {
        matches(request: {take: 100}) {
          startDateTime
          players(steamAccountId: $player_id) {
            isVictory
          }
        }
      }
    }
    '''
    matches_data = query_api(query_matches_week, url, headers, {'player_id': latest_player_id})['player']['matches']
    daily_wins, daily_losses, weekly_wins, weekly_losses = get_win_rates(matches_data)

    daily_wl_str = f"{daily_wins[0]}-{daily_losses[0]}"
    weekly_wl_str = f"{weekly_wins}-{weekly_losses}"

    embed = discord.Embed(title=f"Match ID: {masked_match_id}", color=discord.Color.blue())
    embed.add_field(name="Никнейм:", value=player_data['steamAccount']['name'], inline=True)
    embed.add_field(name="Результат:", value=match_result, inline=True)
    embed.add_field(name="KDA:", value=kda, inline=True)
    embed.add_field(name="Аверага:", value=f"{convert_average_rank_to_medal(match_data['match']['rank'])}", inline=True)
    embed.add_field(name="Дата:", value=match_date, inline=True)
    embed.add_field(name="Длительность:", value=actual_duration, inline=True)
    embed.add_field(name="Роль:", value=get_role(player_data['position']), inline=True)
    embed.add_field(name="Daily W-L:", value=daily_wl_str, inline=True)
    embed.add_field(name="Weekly W-L:", value=weekly_wl_str, inline=True)

    if kda_comment:
        embed.add_field(name="Комментарий:", value=kda_comment, inline=False)

    embed.set_thumbnail(url=hero_image_url)

    embed.description = (
        f"[Dotabuff]({match_url}) | "
        f"[Opendota]({opendota_url}) | "
        f"[Stratz]({stratz_url})"
    )
    await ctx.send(embed=embed)