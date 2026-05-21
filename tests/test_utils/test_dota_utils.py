import pytest

from utils.dota_utils import convert_average_rank_to_medal, get_game_mode, get_role, get_win_rates


@pytest.mark.parametrize(
    "player_position,expected",
    [
        # Короткий формат (legacy / OpenDota совместимость).
        ("1", "Керри"),
        ("2", "Мидер"),
        ("3", "Оффлейнер"),
        ("4", "Саппорт"),
        ("5", "Саппорт"),
        # Реальный формат Stratz GraphQL.
        ("POSITION_1", "Керри"),
        ("POSITION_2", "Мидер"),
        ("POSITION_3", "Оффлейнер"),
        ("POSITION_4", "Саппорт"),
        ("POSITION_5", "Саппорт"),
        # Неизвестные/пустые значения.
        (None, "Неизвестно"),
        ("", "Неизвестно"),
        ("unknown", "Неизвестно"),
        ("POSITION_0", "Неизвестно"),
        ("POSITION_6", "Неизвестно"),
        ("position_1", "Неизвестно"),  # регистр важен — Stratz всегда ВЕРХНИЙ
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
