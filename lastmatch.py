import discord
import logging
from datetime import datetime
from discord.ui import View, Button

# Импортируем только используемые функции
from dota_api import read_json_file, query_api_with_retry, fetch_items_data
from dota_utils import get_role, convert_average_rank_to_medal, get_game_mode, get_win_rates

# Настройка логирования
logger = logging.getLogger("dota_bot")

# Определение цвета для embed
def get_embed_color(is_victory, kda_value):
    if is_victory:
        return discord.Color.green() if kda_value >= 3 else discord.Color.teal()
    else:
        return discord.Color.red() if kda_value < 1.5 else discord.Color.gold()

# Проверка наличия данных в ответе API
def check_api_response(response, *keys):
    """Проверяет наличие всех указанных ключей в ответе API."""
    data = response
    for key in keys:
        if not data or key not in data or not data[key]:
            return False
        data = data[key]
    return True

# Получение строки с предметами
def get_items_string(player_data, items_dict):
    """Формирует строку с предметами игрока."""
    items_str = []
    for i in range(6):
        item_id_field = f"item{i}Id"
        if item_id_field in player_data and player_data[item_id_field] and player_data[item_id_field] > 0:
            item_id = player_data[item_id_field]
            if item_id in items_dict:
                item_name = items_dict[item_id].get('displayName', f"Item {item_id}")
                items_str.append(item_name)
    
    neutral_item_str = ""
    if "neutral0Id" in player_data and player_data["neutral0Id"] and player_data["neutral0Id"] > 0:
        item_id = player_data["neutral0Id"]
        if item_id in items_dict:
            neutral_item_str = items_dict[item_id].get('displayName', f"Item {item_id}")
    
    # Объединяем строки предметов
    all_items_str = ", ".join(items_str)
    if neutral_item_str:
        all_items_str += f" | {neutral_item_str}"
    
    return all_items_str

# Основная функция обработки команды
async def handle_lastmatch(ctx, user_links: dict, member: discord.Member = None):
    try:
        config = read_json_file('config.json')
        
        url = 'https://api.stratz.com/graphql'
        headers = {'Authorization': f'Bearer {config["STRATZ_API_KEY"]}'}
        
        # Определяем ID пользователя
        user_id = str(member.id if member else ctx.author.id)
        if user_id not in user_links or not user_links[user_id]:
            message = f"Пользователь {member.mention} не привязал свой аккаунт Dota 2." if member else "Сначала привяжите ваш аккаунт Discord к аккаунту Dota 2."
            await ctx.send(f"{message} Используйте команду !link PLAYER_ID.")
            return
            
        player_ids = user_links[user_id]
        logger.info(f"Пользователь ID: {user_id}, Найденные аккаунты: {player_ids}")
        
        # Поиск последнего матча
        latest_match = {'id': None, 'startDateTime': 0}
        latest_player_id = None
 
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
            cache_key = f"matches_{player_id}_latest"
            response = query_api_with_retry(query_matches, url, headers, {'player_id': int(player_id)}, cache_key)
            
            # Проверка на ошибки при запросе с помощью новой функции
            if not check_api_response(response, 'player', 'matches'):
                logger.warning(f"Не удалось получить данные для игрока с ID {player_id}")
                continue
                
            matches = response['player']['matches']
            
            if matches and matches[0]['startDateTime'] > latest_match['startDateTime']:
                latest_match = matches[0]
                latest_player_id = player_id
 
        # Проверка на наличие последнего матча
        if latest_match['id'] is None:
            await ctx.send("Не найдено ни одного доступного матча, скорее всего нужно включить доступность истории матчей в клиенте игры.")
            return
            
        # Запрашиваем данные о предметах заранее
        items_dict = fetch_items_data(url, headers)
            
        # Запрос подробной информации о матче и статистики игрока
        query_match = '''
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
        
        cache_key = f"match_{latest_match['id']}_{latest_player_id}"
        match_data = query_api_with_retry(query_match, url, headers, 
                                 {'player_id': int(latest_player_id), 'match_id': int(latest_match['id'])},
                                 cache_key)
        
        # Проверка на ошибки при запросе с помощью новой функции
        if not check_api_response(match_data, 'match', 'players'):
            await ctx.send("Не удалось получить данные о последнем матче. Пожалуйста, попробуйте позже.")
            return
            
        player_data = match_data['match']['players'][0]
        
        # Запрос истории матчей для расчета винрейта
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
        
        cache_key = f"matches_week_{latest_player_id}"
        matches_data_response = query_api_with_retry(query_matches_week, url, headers, 
                                           {'player_id': int(latest_player_id)},
                                           cache_key)
        
        # Подготовка основных данных для отображения
        match_date = datetime.utcfromtimestamp(match_data['match']['startDateTime']).strftime('%d/%m/%Y')
        duration = match_data['match']['durationSeconds']
        actual_duration = f'{duration // 60}:{duration % 60:02}'
        
        is_victory = player_data['isVictory']
        kills = player_data['kills']
        deaths = player_data['deaths']
        assists = player_data['assists']
        kda = f"{kills}/{deaths}/{assists}"
        kda_value = (kills + assists) / max(deaths, 1)
        
        hero_name = player_data['hero']['shortName']
        
        # Получаем режим игры, роль и ранг
        game_mode = get_game_mode(match_data['match'].get('gameMode', 0), match_data['match'].get('lobbyType', None))
        role = get_role(player_data['position'])
        rank = convert_average_rank_to_medal(match_data['match'].get('rank', 0))
        
        # Получаем статистику
        gpm = player_data.get('goldPerMinute', 0)
        xpm = player_data.get('experiencePerMinute', 0)
        gpm_xpm = f"{gpm}/{xpm}"
        
        networth = player_data.get('networth', 0)
        networth_formatted = f"{networth:,}" if networth else "N/A"
        
        hero_damage = player_data.get('heroDamage', 0)
        hero_damage_formatted = f"{hero_damage:,}" if hero_damage else "N/A"
        
        # Получаем комментарий по KDA
        if is_victory:
            kda_comment = "красава разъебал" if kda_value > 4 else "затащили дурака" if kda_value < 2 else "норм сыграл"
        else:
            kda_comment = "старался, команда подвела" if kda_value > 4 else "заруинил пидорас" if kda_value < 2 else "норм сыграл"
            
        # Ссылки на сайты статистики
        match_url = f"https://www.dotabuff.com/matches/{latest_match['id']}"
        stratz_url = f"https://stratz.com/matches/{latest_match['id']}"
        opendota_url = f"https://opendota.com/matches/{latest_match['id']}"
        
        # Рассчитываем статистику побед и поражений
        daily_wl_str = "N/A"
        weekly_wl_str = "N/A"
        
        if check_api_response(matches_data_response, 'player', 'matches'):
            matches_data = matches_data_response['player']['matches']
            daily_wins, daily_losses, weekly_wins, weekly_losses = get_win_rates(matches_data)
            daily_wl_str = f"{daily_wins[0]}-{daily_losses[0]}"
            weekly_wl_str = f"{weekly_wins}-{weekly_losses}"
        
        # Получаем строку с предметами с помощью новой функции
        all_items_str = get_items_string(player_data, items_dict)
        
        # Определяем цвет для embed
        embed_color = get_embed_color(is_victory, kda_value)
        
        # Создаем embed с оптимизированным порядком полей
        embed = discord.Embed(title=f"**{kda_comment}**", color=embed_color)
        
        # 1-я строка: никнейм, роль, kda
        embed.add_field(name="Никнейм:", value=player_data['steamAccount']['name'], inline=True)
        embed.add_field(name="Роль:", value=role, inline=True)
        embed.add_field(name="KDA:", value=kda, inline=True)
        
        # 2-я строка: режим, длительность, аверага
        embed.add_field(name="Режим:", value=game_mode, inline=True)
        embed.add_field(name="Длительность:", value=actual_duration, inline=True)
        embed.add_field(name="Аверага:", value=rank, inline=True)
        
        # 3-я строка: GPM/XPM, Networth, Hero Damage
        embed.add_field(name="GPM/XPM:", value=gpm_xpm, inline=True)
        embed.add_field(name="Networth:", value=networth_formatted, inline=True)
        embed.add_field(name="Hero Damage:", value=hero_damage_formatted, inline=True)
        
        # 4-я строка: Дата, Daily W-L, Weekly W-L
        embed.add_field(name="Дата:", value=match_date, inline=True)
        embed.add_field(name="Daily W-L:", value=daily_wl_str, inline=True)
        embed.add_field(name="Weekly W-L:", value=weekly_wl_str, inline=True)
        
        # Предметы - отдельной строкой внизу
        embed.add_field(name="Предметы:", value=all_items_str, inline=False)

        # Устанавливаем изображение героя
        hero_image_url = f'https://cdn.stratz.com/images/dota2/heroes/{hero_name}_horz.png'
        embed.set_thumbnail(url=hero_image_url)
        
        # Аватар игрока в заголовке (если доступен)
        if player_data['steamAccount'].get('avatar'):
            embed.set_author(name=player_data['steamAccount']['name'], icon_url=player_data['steamAccount']['avatar'])

        # Создаем интерактивные кнопки для ссылок и обновления
        view = View(timeout=180)  # Время жизни кнопок в секундах
        
        # Кнопки для ссылок на сайты
        view.add_item(Button(style=discord.ButtonStyle.link, label="Dotabuff", url=match_url))
        view.add_item(Button(style=discord.ButtonStyle.link, label="OpenDota", url=opendota_url))
        view.add_item(Button(style=discord.ButtonStyle.link, label="Stratz", url=stratz_url))
        
        # Отправляем сообщение с кнопками
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {str(e)}", exc_info=True)
        await ctx.send(f"Произошла ошибка при обработке команды: {str(e)}")