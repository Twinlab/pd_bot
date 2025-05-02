import pytest
from unittest.mock import MagicMock
from utils.activity.helpers import is_application, format_time, format_time_short

# Тесты для is_application
def test_is_application_bot_flag():
    """Проверяет, что функция возвращает True для участников с флагом bot=True"""
    member = MagicMock()
    member.bot = True
    member.name = "Normal User"
    member.roles = []
    
    assert is_application(member) is True

def test_is_application_app_name():
    """Проверяет, что функция возвращает True для участников с именем из списка app_names"""
    member = MagicMock()
    member.bot = False
    member.name = "minecraft bot"
    member.roles = []
    
    assert is_application(member) is True

def test_is_application_app_role():
    """Проверяет, что функция возвращает True для участников с ролью из списка app_role_names"""
    role = MagicMock()
    role.name = "BOT"
    
    member = MagicMock()
    member.bot = False
    member.name = "Normal User"
    member.roles = [role]
    
    assert is_application(member) is True

def test_is_application_normal_user():
    """Проверяет, что функция возвращает False для обычных участников"""
    role = MagicMock()
    role.name = "User"
    
    member = MagicMock()
    member.bot = False
    member.name = "Normal User"
    member.roles = [role]
    
    assert is_application(member) is False

# Тесты для format_time
@pytest.mark.parametrize("seconds, expected", [
    (0, "0 минут"),
    (-10, "0 минут"),
    (30, "0 минут"),  # Меньше минуты
    (60, "1 минута"),
    (120, "2 минуты"),
    (300, "5 минут"),
    (660, "11 минут"),
    (720, "12 минут"),
    (1200, "20 минут"),
    (1260, "21 минута"),
    (3600, "1 час"),
    (3660, "1 час и 1 минута"),
    (3720, "1 час и 2 минуты"),
    (7200, "2 часа"),
    (7260, "2 часа и 1 минута"),
    (7320, "2 часа и 2 минуты"),
    (10800, "3 часа"),
    (11700, "3 часа и 15 минут"),
    (12600, "3 часа и 30 минут"),
    (13500, "3 часа и 45 минут"),
    (18000, "5 часов"),
    (21600, "6 часов"),
    (43200, "12 часов"),
    (86400, "24 часа"),
    (90000, "25 часов"),
    (126000, "35 часов"),
])
def test_format_time(seconds, expected):
    """Проверяет правильность форматирования времени с учетом русской грамматики"""
    assert format_time(seconds) == expected

# Тесты для format_time_short
@pytest.mark.parametrize("seconds, expected", [
    (0, "0m"),
    (-10, "0m"),
    (30, "0m"),  # Меньше минуты
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
])
def test_format_time_short(seconds, expected):
    """Проверяет правильность короткого форматирования времени"""
    assert format_time_short(seconds) == expected
