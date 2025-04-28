from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Dict, Any, Optional
import logging

logger = logging.getLogger("bot.dota")

# --- Функции форматирования данных Dota 2 ---

def get_role(player_position: Optional[str]) -> str:
    """
    Преобразует код позиции игрока (например, 'POSITION_1') в читаемое название роли.

    Args:
        player_position: Строка с кодом позиции из API Stratz.

    Returns:
        Название роли ('Carry', 'Mid', 'Offlane', 'Soft Support', 'Hard Support') или 'Unknown'.
    """
    if not player_position:
         return 'Unknown'
         
    roles = {
        'POSITION_1': 'Carry',
        'POSITION_2': 'Mid',
        'POSITION_3': 'Offlane',
        'POSITION_4': 'Soft Support',
        'POSITION_5': 'Hard Support'
    }
    return roles.get(player_position, 'Unknown')

def convert_average_rank_to_medal(average_rank: Optional[int]) -> str:
    """
    Преобразует числовой ранг Dota 2 (например, 52) в строку с названием медали и звездами ('Legend II').

    Args:
        average_rank: Числовое представление ранга (первая цифра - медаль, вторая - звезды).

    Returns:
        Строка с названием медали и римской цифрой звезд (или 'Unknown').
    """
    if not average_rank or average_rank == 0:
        return 'Unknown'
    
    # Названия медалей по порядку
    medals = ['Herald', 'Guardian', 'Crusader', 'Archon', 'Legend', 'Ancient', 'Divine', 'Immortal']
    # Римские цифры для звезд
    roman_numerals = ['', 'I', 'II', 'III', 'IV', 'V']
    
    try:
        # Извлекаем номер медали (первая цифра) и номер звезд (вторая цифра)
        rank_str = str(average_rank)
        medal_number = int(rank_str[0])
        stars_number = int(rank_str[1]) if len(rank_str) > 1 else 0 # Учитываем случай без звезд
        
        if medal_number < 1 or medal_number > len(medals):
            return 'Unknown'
            
        medal = medals[medal_number - 1] # Получаем название медали по индексу
        
        # У Immortal ранга нет звезд
        if medal_number == 8:
            return medal
        elif 0 <= stars_number < len(roman_numerals):
             return f'{medal} {roman_numerals[stars_number]}' # Возвращаем "Медаль Звезды"
        else:
             return medal # Возвращаем только медаль, если номер звезд некорректен
             
    except (IndexError, ValueError, TypeError): # Ловим возможные ошибки при преобразовании/индексации
        logger.warning(f"Не удалось преобразовать ранг: {average_rank}")
        return 'Unknown'

def get_game_mode(game_mode_id: Optional[int], lobby_type_id: Optional[int] = None) -> str:
    """
    Определяет название режима игры на основе ID режима и ID типа лобби из API Stratz.

    Args:
        game_mode_id: ID режима игры.
        lobby_type_id: ID типа лобби (опционально).

    Returns:
        Строка с названием режима игры (например, "Ranked All Pick", "Turbo", "Unranked").
    """
    if game_mode_id is None:
        return "Unknown"
        
    # Словари соответствия ID и названий
    game_modes = {
        1: "All Pick",
        2: "Captains Mode",
        3: "Random Draft",
        4: "Single Draft",
        5: "All Random",
        22: "All Pick", # Старый ID для All Pick
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
        7: "Ranked", # Общий тип для Ranked
        8: "1v1 Mid",
        9: "Battle Cup"
    }
    
    # Обработка особых комбинаций режима и лобби
    if game_mode_id == 22 and lobby_type_id == 7: # Ranked All Pick (старый ID)
        return "Ranked" # Возвращаем просто "Ranked"
    elif game_mode_id == 22 and lobby_type_id == 0: # Unranked All Pick (старый ID)
        return "Unranked" # Возвращаем просто "Unranked"
    elif game_mode_id == 23: # Turbo
        return "Turbo"
    
    # Получаем названия из словарей или используем ID, если название неизвестно
    game_mode_str = game_modes.get(game_mode_id, f"Mode {game_mode_id}")
    lobby_type_str = lobby_types.get(lobby_type_id, "")
    
    # Комбинируем название лобби и режима, если оба известны
    if lobby_type_str and not game_mode_str.startswith("Mode"):
        # Особый случай для Ranked All Pick
        if lobby_type_id == 7 and game_mode_id == 22:
             return "Ranked"
        return f"{lobby_type_str} {game_mode_str}"
    
    # Если известен только тип лобби
    if lobby_type_str:
        return lobby_type_str
        
    # Если известен только режим (или ничего не известно)
    return game_mode_str

def get_win_rates(player_matches: List[Dict[str, Any]], num_days: int = 7) -> Tuple[List[int], List[int], int, int]:
    """
    Рассчитывает статистику побед и поражений за последние `num_days` дней
    и отдельно за последние 24 часа (первый элемент списков daily_wins/losses).

    Args:
        player_matches: Список словарей с данными матчей игрока (должен содержать 'startDateTime' и 'players').
        num_days: Количество дней для анализа (по умолчанию 7).

    Returns:
        Кортеж: (daily_wins, daily_losses, total_period_wins, total_period_losses).
               Списки daily_* содержат статистику по дням, начиная с сегодня (индекс 0).
    """
    now = datetime.now(timezone.utc) # Текущее время UTC
    # Инициализируем списки для хранения статистики по дням
    daily_wins = [0] * num_days
    daily_losses = [0] * num_days
    # Инициализируем общие счетчики за весь период
    total_period_wins = 0
    total_period_losses = 0
 
    # Обрабатываем каждый матч из списка
    for match in player_matches:
        # Проверяем наличие необходимых данных
        if not match or 'startDateTime' not in match or 'players' not in match or not match['players']:
             logger.warning("Пропуск матча из-за отсутствия данных в get_win_rates")
             continue
             
        # Получаем время начала матча и разницу в днях с текущим моментом
        try:
            match_time = datetime.fromtimestamp(match['startDateTime'], timezone.utc)
        except (TypeError, ValueError):
            logger.warning(f"Некорректный timestamp в матче: {match.get('startDateTime')}")
            continue
            
        delta_days = (now - match_time).days
 
        # Учитываем матч, только если он был сыгран в пределах заданного периода
        if 0 <= delta_days < num_days:
            try:
                # Получаем результат матча для игрока (предполагается, что он первый в списке players)
                is_victory = match['players'][0]['isVictory']
                if is_victory:
                    daily_wins[delta_days] += 1
                    total_period_wins += 1
                else:
                    daily_losses[delta_days] += 1
                    total_period_losses += 1
            except (KeyError, IndexError, TypeError) as e:
                 logger.warning(f"Ошибка при обработке данных матча в get_win_rates: {e}")
 
    return daily_wins, daily_losses, total_period_wins, total_period_losses

# Эта функция больше не используется напрямую в handle_lastmatch, но может быть полезна
def format_match_stats(match_data: Dict[str, Any], player_id: int) -> Dict[str, Any]:
    """
    Извлекает и форматирует ключевую статистику из сырых данных матча,
    полученных от API, в более удобный для использования словарь.
    """
    # Инициализируем словарь с результатами по умолчанию
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
        # Извлекаем общую информацию о матче
        result['game_mode'] = get_game_mode(
            match_data.get('gameMode', 0),
            match_data.get('lobbyType', None)
        )
        result['duration'] = match_data.get('durationSeconds', 0)
        result['start_time'] = datetime.utcfromtimestamp(match_data.get('startDateTime', 0))
        
        # Находим и извлекаем данные конкретного игрока
        player_data = None
        for player in match_data.get('players', []):
            if player.get('steamAccountId') == player_id:
                player_data = player
                break # Нашли нужного игрока, выходим из цикла
                
        if player_data:
                result['is_victory'] = player_data.get('isVictory', False)
                
                result['player']['hero'] = player_data.get('hero', {}).get('displayName', 'Unknown')
                result['player']['hero_id'] = player_data.get('hero', {}).get('id', 0)
                result['player']['kills'] = player_data.get('kills', 0)
                result['player']['deaths'] = player_data.get('deaths', 0)
                result['player']['assists'] = player_data.get('assists', 0)
                result['player']['net_worth'] = player_data.get('networth', 0)
                result['player']['gpm'] = player_data.get('goldPerMinute', 0)
                result['player']['xpm'] = player_data.get('experiencePerMinute', 0)
                
                # Извлекаем информацию о предметах
                # (Примечание: API может возвращать предметы в другом формате, эта часть может требовать адаптации)
                # Эта логика извлечения предметов может быть неактуальна для текущего API Stratz
                # if 'inventory' in player_data:
                #     for item in player_data['inventory']:
                #         if item: # Пропускаем пустые слоты
                #             result['player']['items'].append({
                #                 'id': item.get('id', 0),
                #                 'name': item.get('name', ''),
                #                 'image': item.get('image', '')
                #             })
                
                result['player']['role'] = get_role(player_data.get('position')) # Используем position
        
        # Извлекаем информацию о союзниках и противниках (опционально, если нужно)
        player_team_is_radiant = None
        if player_data:
             player_team_is_radiant = player_data.get('isRadiant')

        if player_team_is_radiant is not None:
            # Заполняем списки союзников и противников
            for player in match_data.get('players', []):
                # Пропускаем самого игрока
                if player.get('steamAccountId') == player_id:
                    continue
                    
                player_info = {
                    'hero': player.get('hero', {}).get('displayName', 'Unknown'),
                    'hero_id': player.get('hero', {}).get('id', 0),
                    'kills': player.get('kills', 0),
                    'deaths': player.get('deaths', 0),
                    'assists': player.get('assists', 0),
                    'player_name': player.get('steamAccount', {}).get('name', 'Unknown'),
                    'role': get_role(player.get('position')), # Используем position
                    'rank': convert_average_rank_to_medal(player.get('steamAccount', {}).get('seasonRank', 0))
                }
            
                # Добавляем в соответствующую команду
                if player.get('isRadiant') == player_team_is_radiant:
                    result['team'].append(player_info)
                else:
                    result['enemy_team'].append(player_info)
    
    except Exception as e:
        logger.error(f"Ошибка при форматировании данных матча: {e}", exc_info=True)
    
    return result
