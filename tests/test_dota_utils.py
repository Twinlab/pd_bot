import pytest

from utils.dota_utils import get_role


@pytest.mark.parametrize(
    "player_position,expected",
    [
        ("1", "Керри"),
        ("2", "Мидер"),
        ("3", "Оффлейнер"),
        ("4", "Саппорт"),
        ("5", "Саппорт"),
        (None, "Неизвестно"),
        ("unknown", "Неизвестно"),
    ],
)
def test_get_role(player_position, expected):
    assert get_role(player_position) == expected
