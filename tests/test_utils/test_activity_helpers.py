from unittest.mock import MagicMock

import pytest

from utils.activity.helpers import format_time_short, is_application


# Тесты для is_application
def test_is_application_bot_flag() -> None:
    """Проверяет, что функция возвращает True для участников с флагом bot=True."""
    member = MagicMock()
    member.bot = True
    member.name = "Normal User"
    member.roles = []

    assert is_application(member) is True


def test_is_application_app_name() -> None:
    """Проверяет, что функция возвращает True для участников с именем из списка app_names."""
    member = MagicMock()
    member.bot = False
    member.name = "minecraft bot"
    member.roles = []

    assert is_application(member) is True


def test_is_application_app_role() -> None:
    """Проверяет, что функция возвращает True для участников с ролью из списка app_role_names."""
    role = MagicMock()
    role.name = "BOT"

    member = MagicMock()
    member.bot = False
    member.name = "Normal User"
    member.roles = [role]

    assert is_application(member) is True


def test_is_application_normal_user() -> None:
    """Проверяет, что функция возвращает False для обычных участников."""
    role = MagicMock()
    role.name = "User"

    member = MagicMock()
    member.bot = False
    member.name = "Normal User"
    member.roles = [role]

    assert is_application(member) is False


# Тесты для format_time_short
@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "0m"),
        (-10, "0m"),
        (1, "<1m"),
        (30, "<1m"),
        (59, "<1m"),
        (60, "1m"),
        (120, "2m"),
        (300, "5m"),
        (3600, "1h"),
        (3660, "1h 1m"),
        (3720, "1h 2m"),
        (7200, "2h"),
        (7260, "2h 1m"),
        (7320, "2h 2m"),
        (10800, "3h"),
        (11700, "3h 15m"),
        (12600, "3h 30m"),
        (13500, "3h 45m"),
        (18000, "5h"),
        (21600, "6h"),
        (43200, "12h"),
        (86400, "24h"),
        (90000, "25h"),
        (126000, "35h"),
    ],
)
def test_format_time_short(seconds: int, expected: str) -> None:
    """Проверяет правильность короткого форматирования времени."""
    assert format_time_short(seconds) == expected
