"""Утилиты для работы с данными Dota 2.

Этот модуль предоставляет функции для форматирования и преобразования данных Dota 2,
полученных из API Stratz, в удобный для отображения формат. Включает функции для
определения роли игрока, преобразования рангов в медали, определения режима игры
и расчета статистики побед/поражений.
"""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("bot.utils.dota_utils")

# --- Функции форматирования данных Dota 2 ---


def get_role(player_position: str | None) -> str:
    """Преобразует номер позиции игрока в читаемое название роли.

    Args:
        player_position: Строка с номером позиции ('1'-'5'), либо None.

    Returns:
        Название роли ('Керри', 'Мидер', 'Оффлейнер', 'Саппорт') или 'Неизвестно'.
    """
    if not player_position:
        return "Неизвестно"
    roles = {"1": "Керри", "2": "Мидер", "3": "Оффлейнер", "4": "Саппорт", "5": "Саппорт"}
    return roles.get(str(player_position), "Неизвестно")


def convert_average_rank_to_medal(average_rank: int | None) -> str:
    """Преобразует числовой ранг Dota 2 в строку с названием медали и звездами.

    Например, 52 -> 'Legend II'.

    Args:
        average_rank: Числовое представление ранга (первая цифра - медаль, вторая - звезды).

    Returns:
        Строка с названием медали и римской цифрой звезд (или 'Unknown').
    """
    if not average_rank or average_rank == 0:
        return "Unknown"

    # Названия медалей по порядку
    medals = ["Herald", "Guardian", "Crusader", "Archon", "Legend", "Ancient", "Divine", "Immortal"]
    # Римские цифры для звезд
    roman_numerals = ["", "I", "II", "III", "IV", "V"]

    try:
        # Извлекаем номер медали (первая цифра) и номер звезд (вторая цифра)
        rank_str = str(average_rank)
        medal_number = int(rank_str[0])
        stars_number = int(rank_str[1]) if len(rank_str) > 1 else 0  # Учитываем случай без звезд

        if medal_number < 1 or medal_number > len(medals):
            return "Unknown"

        medal = medals[medal_number - 1]  # Получаем название медали по индексу

        # У Immortal ранга нет звезд
        if medal_number == 8:
            return medal
        elif 0 <= stars_number < len(roman_numerals):
            return f"{medal} {roman_numerals[stars_number]}"  # Возвращаем "Медаль Звезды"
        else:
            return medal  # Возвращаем только медаль, если номер звезд некорректен

    except (
        IndexError,
        ValueError,
        TypeError,
    ):  # Ловим возможные ошибки при преобразовании/индексации
        logger.warning(f"Не удалось преобразовать ранг: {average_rank}")
        return "Unknown"


def get_game_mode(game_mode_id: int | None, lobby_type_id: int | None = None) -> str:
    """Определяет название режима игры на основе ID режима и ID типа лобби из API Stratz.

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
        22: "All Pick",  # Старый ID для All Pick
        23: "Turbo",
    }

    lobby_types = {
        0: "Normal",
        1: "Practice",
        2: "Tournament",
        3: "Tutorial",
        4: "Co-op Bots",
        5: "Ranked Team MM",
        6: "Ranked Solo MM",
        7: "Ranked",  # Общий тип для Ranked
        8: "1v1 Mid",
        9: "Battle Cup",
    }

    # Обработка особых комбинаций режима и лобби
    if game_mode_id == 22 and lobby_type_id == 7:  # Ranked All Pick (старый ID)
        return "Ranked"  # Возвращаем просто "Ranked"
    elif game_mode_id == 22 and lobby_type_id == 0:  # Unranked All Pick (старый ID)
        return "Unranked"  # Возвращаем просто "Unranked"
    elif game_mode_id == 23:  # Turbo
        return "Turbo"

    # Получаем названия из словарей или используем ID, если название неизвестно
    # Проверяем, что game_mode_id не None перед использованием get
    game_mode_str = (
        game_modes.get(game_mode_id, f"Mode {game_mode_id}")
        if game_mode_id is not None
        else "Unknown Mode"
    )
    # Проверяем, что lobby_type_id не None перед использованием get
    lobby_type_str = lobby_types.get(lobby_type_id, "") if lobby_type_id is not None else ""

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


def get_win_rates(
    player_matches: list[dict[str, Any]], num_days: int = 7
) -> tuple[list[int], list[int], int, int]:
    """Рассчитывает статистику побед и поражений за последние `num_days` дней.

    Также отдельно за последние 24 часа (первый элемент списков daily_wins/losses).

    Args:
        player_matches: Список словарей с данными матчей игрока
            (должен содержать 'startDateTime' и 'players').
        num_days: Количество дней для анализа (по умолчанию 7).

    Returns:
        Кортеж: (daily_wins, daily_losses, total_period_wins, total_period_losses).
               Списки daily_* содержат статистику по дням, начиная с сегодня (индекс 0).
    """
    now = datetime.now(UTC)  # Текущее время UTC
    # Инициализируем списки для хранения статистики по дням
    daily_wins = [0] * num_days
    daily_losses = [0] * num_days
    # Инициализируем общие счетчики за весь период
    total_period_wins = 0
    total_period_losses = 0

    # Обрабатываем каждый матч из списка
    for match in player_matches:
        # Проверяем наличие необходимых данных
        if (
            not match
            or "startDateTime" not in match
            or "players" not in match
            or not match["players"]
        ):
            logger.warning("Пропуск матча из-за отсутствия данных в get_win_rates")
            continue

        # Получаем время начала матча и разницу в днях с текущим моментом
        try:
            match_time = datetime.fromtimestamp(match["startDateTime"], UTC)
        except (TypeError, ValueError):
            logger.warning(f"Некорректный timestamp в матче: {match.get('startDateTime')}")
            continue

        delta_days = (now - match_time).days

        # Учитываем матч, только если он был сыгран в пределах заданного периода
        if 0 <= delta_days < num_days:
            try:
                # Получаем результат матча для игрока
                # (предполагается, что он первый в списке players)
                is_victory = match["players"][0]["isVictory"]
                if is_victory:
                    daily_wins[delta_days] += 1
                    total_period_wins += 1
                else:
                    daily_losses[delta_days] += 1
                    total_period_losses += 1
            except (KeyError, IndexError, TypeError) as e:
                logger.warning(f"Ошибка при обработке данных матча в get_win_rates: {e}")

    return daily_wins, daily_losses, total_period_wins, total_period_losses
