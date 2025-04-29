from utils.dota_utils import (
    get_role,
    convert_average_rank_to_medal,
    get_game_mode,
    get_win_rates,
    format_match_stats,
)

def test_get_role():
    assert get_role("1") == "Керри"
    assert get_role("2") == "Мидер"
    assert get_role("3") == "Оффлейнер"
    assert get_role("4") == "Саппорт"
    assert get_role("5") == "Саппорт"
    assert get_role(None) == "Неизвестно"
    assert get_role("unknown") == "Неизвестно"

def test_convert_average_rank_to_medal():
    assert isinstance(convert_average_rank_to_medal(1000), str)
    assert isinstance(convert_average_rank_to_medal(None), str)

def test_get_game_mode():
    assert isinstance(get_game_mode(1), str)
    assert isinstance(get_game_mode(None), str)
    assert isinstance(get_game_mode(1, 2), str)

def test_get_win_rates():
    matches = [
        {"win": True, "startTime": 1, "player_slot": 0, "radiant_win": True, "steamAccountId": 1},
        {"win": False, "startTime": 2, "player_slot": 1, "radiant_win": False, "steamAccountId": 1},
    ]
    result = get_win_rates(matches, num_days=7)
    assert isinstance(result, tuple)
    assert len(result) == 4

def test_format_match_stats():
    match_data = {
        "kills": 10,
        "deaths": 2,
        "assists": 5,
        "duration": 3600,
        "win": True,
        "startTime": 1,
        "player_slot": 0,
        "radiant_win": True,
        "steamAccountId": 1,
    }
    player_id = 1
    result = format_match_stats(match_data, player_id)
    assert isinstance(result, dict)
