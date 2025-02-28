# dota_utils.py
from datetime import datetime
 
# Функция для преобразования позиции игрока в роль
def get_role(player_role):
    roles = {
        'POSITION_1': 'Carry',
        'POSITION_2': 'Mid',
        'POSITION_3': 'Offlane',
        'POSITION_4': 'Soft Support',
        'POSITION_5': 'Hard Support'
    }
    return roles.get(player_role, 'Unknown')
 
# Функция для преобразования среднего ранга в медаль
def convert_average_rank_to_medal(average_rank):
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
def get_game_mode(game_mode_id, lobby_type_id=None):
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