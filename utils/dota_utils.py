# utils/dota_utils.py
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional
import logging

logger = logging.getLogger("dota_bot")

# Функция для преобразования позиции игрока в роль
def get_role(player_role: str) -> str:
    """
    Преобразует код роли игрока в читаемую строку.
    
    Args:
        player_role: Код роли (например, 'POSITION_1')
        
    Returns:
        Название роли (например, 'Carry')
    """
    roles = {
        'POSITION_1': 'Carry',
        'POSITION_2': 'Mid',
        'POSITION_3': 'Offlane',
        'POSITION_4': 'Soft Support',
        'POSITION_5': 'Hard Support'
    }
    return roles.get(player_role, 'Unknown')

# Функция для преобразования среднего ранга в медаль
def convert_average_rank_to_medal(average_rank: int) -> str:
    """
    Преобразует числовой ранг в название медали с подразделением.
    
    Args:
        average_rank: Числовой ранг (например, 52 для Legend II)
        
    Returns:
        Название медали с подразделением (например, 'Legend II')
    """
    if average_rank == 0:
        return 'Unknown'
    
    medals = ['Herald', 'Guardian', 'Crusader', 'Archon', 'Legend', 'Ancient', 'Divine', 'Immortal']
    roman_numerals = ['', 'I', 'II', 'III', 'IV', 'V']
    
    try:
        medal_number = int(str(average_rank)[0])
        stars_number = int(str(average_rank)[1])
        
        if medal_number < 1 or medal_number > 8:
            return 'Unknown'
            
        medal = medals[medal_number-1]
        
        if medal_number == 8:  # Immortals doesn't have stars
            return medal
        else:
            return f'{medal} {roman_numerals[stars_number]}'
    except (IndexError, ValueError):
        return 'Unknown'

# Функция для получения режима игры
def get_game_mode(game_mode_id: int, lobby_type_id: Optional[int] = None) -> str:
    """
    Определяет режим игры на основе ID режима и типа лобби.
    
    Args:
        game_mode_id: ID режима игры
        lobby_type_id: ID типа лобби (опционально)
        
    Returns:
        Название режима игры
    """
    game_modes = {
        1: "All Pick",
        2: "Captains Mode",
        3: "Random Draft",
        4: "Single Draft",
        5: "All Random",
        22: "All Pick",
        23: "Turbo"
    }
    
    lobby_types = {
        0: "Normal",
        1: "Practice",
        2: "Tournament",
        3: "Tutorial",
        4: "Co-op Bots",
        5: "Ranked Team MM",
        6: "Ranked Solo MM",
        7: "Ranked",
        8: "1v1 Mid",
        9: "Battle Cup"
    }
    
    # Для некоторых специальных случаев
    if game_mode_id == 22 and lobby_type_id in [5, 6, 7]:
        return "Ranked"
    elif game_mode_id == 22 and lobby_type_id == 0:
        return "Unranked"
    elif game_mode_id == 23:
        return "Turbo"
    
    # Проверяем есть ли значение в словаре, иначе возвращаем Unknown
    game_mode_str = game_modes.get(game_mode_id, f"{game_mode_id}")
    lobby_type_str = lobby_types.get(lobby_type_id, "")
    
    # Комбинируем информацию о режиме и типе лобби
    if lobby_type_str and game_mode_str != f"{game_mode_id}":
        return f"{lobby_type_str} {game_mode_str}"
    
    # Если нет информации о режиме, пытаемся хотя бы вернуть тип лобби
    if lobby_type_str:
        return lobby_type_str
        
    return game_mode_str

# Функция для расчета дневного и недельного винрейта
def get_win_rates(player_matches: List[Dict[str, Any]], days: int = 7) -> Tuple[List[int], List[int], int, int]:
    """
    Рассчитывает дневной и недельный винрейт игрока.
    
    Args:
        player_matches: Список матчей игрока
        days: Количество дней для анализа
        
    Returns:
        Кортеж из четырех элементов:
        - Список побед по дням
        - Список поражений по дням
        - Общее количество побед за неделю
        - Общее количество поражений за неделю
    """
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

# Функция для форматирования статистики матча
def format_match_stats(match_data: Dict[str, Any], player_id: int) -> Dict[str, Any]:
    """
    Форматирует данные матча для удобного отображения.
    
    Args:
        match_data: Данные матча из API
        player_id: ID игрока, чью статистику нужно выделить
        
    Returns:
        Словарь с отформатированной статистикой
    """
    result = {
        'match_id': match_data.get('matchId', 0),
        'game_mode': 'Unknown',
        'duration': 0,
        'start_time': None,
        'is_victory': False,
        'player': {
            'hero': 'Unknown',
            'hero_id': 0,
            'kills': 0,
            'deaths': 0,
            'assists': 0,
            'net_worth': 0,
            'gpm': 0,
            'xpm': 0,
            'items': [],
            'role': 'Unknown'
        },
        'team': [],
        'enemy_team': []
    }
    
    try:
        # Общая информация о матче
        result['game_mode'] = get_game_mode(
            match_data.get('gameMode', 0),
            match_data.get('lobbyType', None)
        )
        result['duration'] = match_data.get('durationSeconds', 0)
        result['start_time'] = datetime.utcfromtimestamp(match_data.get('startDateTime', 0))
        
        # Информация об игроке
        for player in match_data.get('players', []):
            if player.get('steamAccountId') == player_id:
                result['is_victory'] = player.get('isVictory', False)
                
                result['player']['hero'] = player.get('hero', {}).get('displayName', 'Unknown')
                result['player']['hero_id'] = player.get('hero', {}).get('id', 0)
                result['player']['kills'] = player.get('kills', 0)
                result['player']['deaths'] = player.get('deaths', 0)
                result['player']['assists'] = player.get('assists', 0)
                result['player']['net_worth'] = player.get('networth', 0)
                result['player']['gpm'] = player.get('goldPerMinute', 0)
                result['player']['xpm'] = player.get('experiencePerMinute', 0)
                
                # Предметы игрока
                if 'inventory' in player:
                    for item in player['inventory']:
                        if item:
                            result['player']['items'].append({
                                'id': item.get('id', 0),
                                'name': item.get('name', ''),
                                'image': item.get('image', '')
                            })
                
                result['player']['role'] = get_role(player.get('role', 'Unknown'))
                break
        
        # Информация о командах
        team_id = None
        for player in match_data.get('players', []):
            if player.get('steamAccountId') == player_id:
                team_id = player.get('isRadiant', True)
                break
        
        # Заполняем команды
        for player in match_data.get('players', []):
            player_info = {
                'hero': player.get('hero', {}).get('displayName', 'Unknown'),
                'hero_id': player.get('hero', {}).get('id', 0),
                'kills': player.get('kills', 0),
                'deaths': player.get('deaths', 0),
                'assists': player.get('assists', 0),
                'player_name': player.get('steamAccount', {}).get('name', 'Unknown'),
                'role': get_role(player.get('role', 'Unknown')),
                'rank': convert_average_rank_to_medal(player.get('steamAccount', {}).get('seasonRank', 0))
            }
            
            if player.get('isRadiant', True) == team_id:
                result['team'].append(player_info)
            else:
                result['enemy_team'].append(player_info)
    
    except Exception as e:
        logger.error(f"Ошибка при форматировании данных матча: {e}")
    
    return result

# Функция для генерации сводной статистики по нескольким матчам
def generate_summary_stats(matches: List[Dict[str, Any]], player_id: int) -> Dict[str, Any]:
    """
    Генерирует сводную статистику по нескольким матчам.
    
    Args:
        matches: Список матчей
        player_id: ID игрока
        
    Returns:
        Словарь со сводной статистикой
    """
    if not matches:
        return {
            'matches_count': 0,
            'winrate': 0,
            'avg_kills': 0,
            'avg_deaths': 0,
            'avg_assists': 0,
            'avg_gpm': 0,
            'avg_xpm': 0,
            'most_played_heroes': []
        }
    
    stats = {
        'matches_count': len(matches),
        'wins': 0,
        'losses': 0,
        'total_kills': 0,
        'total_deaths': 0,
        'total_assists': 0,
        'total_gpm': 0,
        'total_xpm': 0,
        'heroes': {}
    }
    
    for match in matches:
        formatted_match = format_match_stats(match, player_id)
        
        if formatted_match['is_victory']:
            stats['wins'] += 1
        else:
            stats['losses'] += 1
        
        stats['total_kills'] += formatted_match['player']['kills']
        stats['total_deaths'] += formatted_match['player']['deaths']
        stats['total_assists'] += formatted_match['player']['assists']
        stats['total_gpm'] += formatted_match['player']['gpm']
        stats['total_xpm'] += formatted_match['player']['xpm']
        
        # Подсчет героев
        hero_id = formatted_match['player']['hero_id']
        hero_name = formatted_match['player']['hero']
        
        if hero_id not in stats['heroes']:
            stats['heroes'][hero_id] = {
                'name': hero_name,
                'matches': 0,
                'wins': 0
            }
        
        stats['heroes'][hero_id]['matches'] += 1
        if formatted_match['is_victory']:
            stats['heroes'][hero_id]['wins'] += 1
    
    # Расчет средних значений
    result = {
        'matches_count': stats['matches_count'],
        'winrate': (stats['wins'] / stats['matches_count']) * 100 if stats['matches_count'] > 0 else 0,
        'avg_kills': stats['total_kills'] / stats['matches_count'] if stats['matches_count'] > 0 else 0,
        'avg_deaths': stats['total_deaths'] / stats['matches_count'] if stats['matches_count'] > 0 else 0,
        'avg_assists': stats['total_assists'] / stats['matches_count'] if stats['matches_count'] > 0 else 0,
        'avg_gpm': stats['total_gpm'] / stats['matches_count'] if stats['matches_count'] > 0 else 0,
        'avg_xpm': stats['total_xpm'] / stats['matches_count'] if stats['matches_count'] > 0 else 0
    }
    
    # Сортировка героев по количеству матчей
    heroes_sorted = sorted(
        [{'id': k, **v} for k, v in stats['heroes'].items()],
        key=lambda x: x['matches'],
        reverse=True
    )
    
    result['most_played_heroes'] = [
        {
            'name': hero['name'],
            'matches': hero['matches'],
            'winrate': (hero['wins'] / hero['matches']) * 100 if hero['matches'] > 0 else 0
        }
        for hero in heroes_sorted[:5]  # Топ-5 героев
    ]
    
    return result
    