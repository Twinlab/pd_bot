#dota_match_utils.py
import discord
import logging
from datetime import datetime
from discord.ui import View, Button
from typing import Dict, List, Tuple, Optional, Any

# Импорт других утилит
from utils.dota_api import read_json_file, query_api_with_retry, fetch_items_data
from utils.dota_utils import get_role, convert_average_rank_to_medal, get_game_mode, get_win_rates

logger = logging.getLogger("dota_bot")

# GraphQL запросы
QUERY_MATCHES = '''
query ($player_id: Long!) {
  player(steamAccountId: $player_id) {
    matches(request: {take: 1}) {
      id
      startDateTime
    }
  }
}
'''

QUERY_MATCH = '''
query ($player_id: Long!, $match_id: Long!) {
  match(id: $match_id) {
    startDateTime
    durationSeconds
    rank
    gameMode
    lobbyType
    players(steamAccountId: $player_id) {
      steamAccount {
        name
        avatar
      }
      hero {
        shortName
      }
      position
      kills
      deaths
      assists
      goldPerMinute
      experiencePerMinute
      networth
      heroDamage
      isVictory
      item0Id
      item1Id
      item2Id
      item3Id
      item4Id
      item5Id
      neutral0Id
    }
  }
}
'''

QUERY_WEEKLY = '''
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

async def get_match_data(user_links, user_id):
    """Получает данные о последнем матче для отображения"""
    if user_id not in user_links or not user_links[user_id]:
        return None, None, None, None
    
    config = await read_json_file('data/config.json')
    url = 'https://api.stratz.com/graphql'
    headers = {'Authorization': f'Bearer {config["STRATZ_API_KEY"]}'}
    
    # Поиск самого свежего матча среди всех привязанных аккаунтов
    latest_match = {'id': None, 'startDateTime': 0}
    latest_player_id = None
    
    for player_id in user_links[user_id]:
        cache_key = f"matches_{player_id}_latest"
        response = await query_api_with_retry(QUERY_MATCHES, url, headers, {'player_id': player_id}, cache_key)
        
        if response and 'player' in response and 'matches' in response['player'] and response['player']['matches']:
            matches = response['player']['matches']
            if matches[0]['startDateTime'] > latest_match['startDateTime']:
                latest_match = matches[0]
                latest_player_id = player_id
    
    if latest_match['id'] is None:
        return None, None, None, None
    
    # Получаем данные о матче
    match_id = latest_match['id']
    cache_key = f"match_{match_id}_{latest_player_id}"
    match_data = await query_api_with_retry(QUERY_MATCH, url, headers, 
                           {'player_id': latest_player_id, 'match_id': match_id}, cache_key)
    
    if not match_data or 'match' not in match_data or 'players' not in match_data['match']:
        return None, None, None, None
    
    # Получаем статистику за неделю
    cache_key = f"matches_week_{latest_player_id}"
    weekly_data = await query_api_with_retry(QUERY_WEEKLY, url, headers, 
                              {'player_id': latest_player_id}, cache_key)
    
    # Получаем данные о предметах
    items_dict = await fetch_items_data(url, headers)
    
    return match_data, weekly_data, match_id, items_dict

async def handle_lastmatch(ctx, user_links, member=None):
    """Обработчик команды lastmatch - показывает информацию о последнем матче"""
    try:
        user_id = str(member.id if member else ctx.author.id)
        
        # Проверяем наличие привязок
        if user_id not in user_links or not user_links[user_id]:
            message = f"Пользователь {member.mention} не привязал свой аккаунт Dota 2." if member else "Сначала привяжите ваш аккаунт Discord к аккаунту Dota 2."
            await ctx.send(f"{message} Используйте команду /link PLAYER_ID.")
            return
            
        # Получаем все необходимые данные
        match_data, weekly_data, match_id, items_dict = await get_match_data(user_links, user_id)
        
        if not match_data:
            await ctx.send("Не удалось получить данные о последнем матче. Убедитесь, что история матчей доступна в настройках Dota 2.")
            return
            
        # Извлекаем данные игрока
        player_data = match_data['match']['players'][0]
        
        # Основные данные матча
        datetime_obj = datetime.utcfromtimestamp(match_data['match']['startDateTime'])
        duration = match_data['match']['durationSeconds']
        is_victory = player_data['isVictory']
        
        # KDA и статистика
        kills, deaths, assists = player_data['kills'], player_data['deaths'], player_data['assists']
        kda_value = (kills + assists) / max(deaths, 1)
        
        # Комментарий на основе KDA
        if is_victory:
            kda_comment = "красава разъебал" if kda_value > 4 else "затащили дурака" if kda_value < 2 else "норм сыграл"
        else:
            kda_comment = "старался, команда подвела" if kda_value > 4 else "заруинил пидорас" if kda_value < 2 else "норм сыграл"
        
        # Определяем цвет эмбеда
        embed_color = discord.Color.green() if is_victory and kda_value >= 3 else discord.Color.teal() if is_victory else discord.Color.red() if kda_value < 1.5 else discord.Color.gold()
        
        # Создаем embed
        embed = discord.Embed(title=f"**{kda_comment}**", color=embed_color)
        
        # Общие данные
        hero_name = player_data['hero']['shortName']
        game_mode = get_game_mode(match_data['match'].get('gameMode', 0), match_data['match'].get('lobbyType', None))
        role = get_role(player_data['position'])
        rank = convert_average_rank_to_medal(match_data['match'].get('rank', 0))
        
        # Добавляем поля в embed
        embed.add_field(name="Никнейм:", value=player_data['steamAccount']['name'], inline=True)
        embed.add_field(name="Роль:", value=role, inline=True)
        embed.add_field(name="KDA:", value=f"{kills}/{deaths}/{assists}", inline=True)
        
        embed.add_field(name="Режим:", value=game_mode, inline=True)
        embed.add_field(name="Длительность:", value=f'{duration // 60}:{duration % 60:02}', inline=True)
        embed.add_field(name="Аверага:", value=rank, inline=True)
        
        embed.add_field(name="GPM/XPM:", value=f"{player_data.get('goldPerMinute', 0)}/{player_data.get('experiencePerMinute', 0)}", inline=True)
        embed.add_field(name="Networth:", value=f"{player_data.get('networth', 0):,}" if player_data.get('networth') else "N/A", inline=True)
        embed.add_field(name="Hero Damage:", value=f"{player_data.get('heroDamage', 0):,}" if player_data.get('heroDamage') else "N/A", inline=True)
        
        # Статистика винрейта
        daily_wl_str, weekly_wl_str = "N/A", "N/A"
        if weekly_data and 'player' in weekly_data and 'matches' in weekly_data['player']:
            matches_data = weekly_data['player']['matches']
            daily_wins, daily_losses, weekly_wins, weekly_losses = get_win_rates(matches_data)
            daily_wl_str = f"{daily_wins[0]}-{daily_losses[0]}"
            weekly_wl_str = f"{weekly_wins}-{weekly_losses}"
        
        embed.add_field(name="Дата:", value=datetime_obj.strftime('%d/%m/%Y'), inline=True)
        embed.add_field(name="Daily W-L:", value=daily_wl_str, inline=True)
        embed.add_field(name="Weekly W-L:", value=weekly_wl_str, inline=True)
        
        # Предметы
        items_str = []
        for i in range(6):
            item_id = player_data.get(f"item{i}Id")
            if item_id and item_id > 0 and item_id in items_dict:
                items_str.append(items_dict[item_id].get('displayName', f"Item {item_id}"))
        
        # Нейтральный предмет
        neutral_id = player_data.get("neutral0Id")
        neutral_str = ""
        if neutral_id and neutral_id > 0 and neutral_id in items_dict:
            neutral_str = f" | {items_dict[neutral_id].get('displayName', f'Item {neutral_id}')}"
        
        all_items = ", ".join(items_str) + neutral_str
        embed.add_field(name="Предметы:", value=all_items or "Нет предметов", inline=False)
        
        # Изображение героя и аватар игрока
        embed.set_thumbnail(url=f'https://cdn.stratz.com/images/dota2/heroes/{hero_name}_horz.png')
        if player_data['steamAccount'].get('avatar'):
            embed.set_author(name=player_data['steamAccount']['name'], icon_url=player_data['steamAccount']['avatar'])
        
        # Создаем кнопки-ссылки
        view = View(timeout=180)
        view.add_item(Button(style=discord.ButtonStyle.link, label="Dotabuff", url=f"https://www.dotabuff.com/matches/{match_id}"))
        view.add_item(Button(style=discord.ButtonStyle.link, label="OpenDota", url=f"https://opendota.com/matches/{match_id}"))
        view.add_item(Button(style=discord.ButtonStyle.link, label="Stratz", url=f"https://stratz.com/matches/{match_id}"))
        
        # Отправляем сообщение
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        logger.error(f"Ошибка при получении данных матча: {e}", exc_info=True)
        await ctx.send(f"Произошла ошибка при обработке команды: {e}")