from utils.dota_utils import convert_average_rank_to_medal, get_game_mode, get_role, get_win_rates


def test_get_role() -> None:
    assert get_role("1") == "Керри"
    assert get_role("2") == "Мидер"
    assert get_role("3") == "Оффлейнер"
    assert get_role("4") == "Саппорт"
    assert get_role("5") == "Саппорт"
    assert get_role(None) == "Неизвестно"
    assert get_role("unknown") == "Неизвестно"


def test_convert_average_rank_to_medal() -> None:
    assert isinstance(convert_average_rank_to_medal(1000), str)
    assert isinstance(convert_average_rank_to_medal(None), str)


def test_get_game_mode() -> None:
    assert isinstance(get_game_mode(1), str)
    assert isinstance(get_game_mode(None), str)
    assert isinstance(get_game_mode(1, 2), str)


def test_get_win_rates() -> None:
    matches = [
        {"win": True, "startTime": 1, "player_slot": 0, "radiant_win": True, "steamAccountId": 1},
        {"win": False, "startTime": 2, "player_slot": 1, "radiant_win": False, "steamAccountId": 1},
    ]
    result = get_win_rates(matches, num_days=7)
    assert isinstance(result, tuple)
    assert len(result) == 4
