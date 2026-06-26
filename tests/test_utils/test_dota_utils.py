import pytest

from utils.dota_utils import convert_average_rank_to_medal, get_game_mode, get_role, get_win_rates


@pytest.mark.parametrize(
    "player_position,expected",
    [
        # Короткий формат (legacy / OpenDota совместимость).
        ("1", "Carry"),
        ("2", "Mid"),
        ("3", "Offlane"),
        ("4", "Support"),
        ("5", "Support"),
        # Реальный формат Stratz GraphQL.
        ("POSITION_1", "Carry"),
        ("POSITION_2", "Mid"),
        ("POSITION_3", "Offlane"),
        ("POSITION_4", "Support"),
        ("POSITION_5", "Support"),
        # Неизвестные/пустые значения.
        (None, "Unknown"),
        ("", "Unknown"),
        ("unknown", "Unknown"),
        ("POSITION_0", "Unknown"),
        ("POSITION_6", "Unknown"),
        ("position_1", "Unknown"),  # регистр важен — Stratz всегда ВЕРХНИЙ
    ],
)
def test_get_role(player_position: str | None, expected: str) -> None:
    assert get_role(player_position) == expected


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
