"""Утилиты для получения и отображения информации о матчах Dota 2.

Этот модуль предоставляет функции для запроса данных о последних матчах игроков Dota 2
через API Stratz, обработки полученной информации и отображения её в виде эмбедов Discord.
Включает GraphQL запросы, функции форматирования данных и создания интерактивных сообщений.
"""

import asyncio
import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands  # Для type hint в docstring
from discord.ui import Button

# Импорт других утилит
from utils.dota_api import fetch_items_data, query_api_with_retry
from utils.dota_utils import convert_average_rank_to_medal, get_game_mode, get_role, get_win_rates

logger = logging.getLogger("bot.utils.dota_match_utils")

# GraphQL запросы к API Stratz
QUERY_MATCHES = """
query ($player_id: Long!) {
  player(steamAccountId: $player_id) {
    matches(request: {take: 1}) { # Запрашиваем только 1 последний матч
      id
      startDateTime
    }
  }
}
"""

QUERY_MATCH = """
query ($player_id: Long!, $match_id: Long!) {
  match(id: $match_id) {
    startDateTime
    durationSeconds
    rank # Средний ранг матча
    gameMode
    lobbyType
    players(steamAccountId: $player_id) { # Данные конкретного игрока
      steamAccount {
        name
        avatar
      }
      hero {
        shortName # Для URL картинки
      }
      position # Роль (POSITION_1 и т.д.)
      kills
      deaths
      assists
      goldPerMinute
      experiencePerMinute
      networth
      heroDamage
      isVictory # Результат матча для игрока
      # Предметы
      item0Id
      item1Id
      item2Id
      item3Id
      item4Id
      item5Id
      neutral0Id # Нейтральный предмет
    }
  }
}
"""

QUERY_WEEKLY = """
query ($player_id: Long!) {
  player(steamAccountId: $player_id) {
    matches(request: {take: 100}) { # Берем последние 100 матчей для статистики
      startDateTime
      players(steamAccountId: $player_id) {
        isVictory # Нужен только результат матча
      }
    }
  }
}
"""


async def get_match_data(
    user_links: dict[str, list[int]], user_id: str, stratz_api_key: str
) -> tuple[dict | None, dict | None, int | None, dict | None]:
    """Получает данные о последнем матче Dota 2 для указанного Discord пользователя.

    Находит самый свежий матч среди всех привязанных Steam ID,
    запрашивает детали матча, недельную статистику и данные о предметах через API Stratz.

    Args:
        user_links: Словарь привязок Discord ID к списку Steam ID.
        user_id: Discord ID пользователя.
        stratz_api_key: Ключ API Stratz.

    Returns:
        Кортеж (match_data, weekly_data, match_id, items_dict)
        или (None, None, None, None) в случае ошибки.
    """
    if user_id not in user_links or not user_links[user_id]:
        logger.warning(f"Нет привязанных аккаунтов для пользователя {user_id}")
        return None, None, None, None

    if not stratz_api_key:
        logger.error("STRATZ_API_KEY не предоставлен для get_match_data")
        return None, None, None, None

    url = "https://api.stratz.com/graphql"
    headers = {"Authorization": f"Bearer {stratz_api_key}"}
    logger.info(
        f"Используется ключ Stratz API: ...{stratz_api_key[-4:] if stratz_api_key else 'None'}"
    )

    # 1. Находим самый последний матч среди всех привязанных Steam ID пользователя.
    # Запросы Stratz по разным Steam ID не зависят друг от друга, поэтому пускаем
    # их параллельно через asyncio.gather. Latency = max(t_i), а не sum(t_i).
    logger.debug(
        f"Поиск последнего матча для Discord ID {user_id} среди Steam ID: {user_links[user_id]}"
    )
    player_ids = list(user_links[user_id])
    matches_responses = await asyncio.gather(
        *(
            query_api_with_retry(
                QUERY_MATCHES,
                url,
                headers,
                {"player_id": player_id},
                f"matches_{player_id}_latest",
            )
            for player_id in player_ids
        ),
        return_exceptions=True,
    )

    latest_match: dict = {"id": None, "startDateTime": 0}
    latest_player_id: int | None = None

    for player_id, response in zip(player_ids, matches_responses, strict=True):
        if isinstance(response, BaseException):
            logger.warning("Ошибка при запросе матчей для Steam ID %s: %s", player_id, response)
            continue
        if response and response.get("player") and response["player"].get("matches"):
            match = response["player"]["matches"][0]
            if match["startDateTime"] > latest_match["startDateTime"]:
                latest_match = match
                latest_player_id = player_id
                logger.debug(f"Найден более новый матч {match['id']} для Steam ID {player_id}")

    # Если не найдено ни одного матча ни для одного Steam ID
    if latest_match["id"] is None:
        logger.warning(f"Не найдено матчей для пользователя {user_id}")
        return None, None, None, None

    logger.info(
        f"Последний матч для {user_id}: ID {latest_match['id']} (Steam ID: {latest_player_id})"
    )

    # 2. Параллельно тянем три независимых запроса:
    #    - детали матча (QUERY_MATCH);
    #    - недельную статистику игрока (QUERY_WEEKLY);
    #    - словарь предметов (fetch_items_data, чаще всего из кэша).
    match_id = latest_match["id"]
    match_data, weekly_data, items_dict = await asyncio.gather(
        query_api_with_retry(
            QUERY_MATCH,
            url,
            headers,
            {"player_id": latest_player_id, "match_id": match_id},
            f"match_{match_id}_{latest_player_id}",
        ),
        query_api_with_retry(
            QUERY_WEEKLY,
            url,
            headers,
            {"player_id": latest_player_id},
            f"matches_week_{latest_player_id}",
        ),
        fetch_items_data(url, headers),
    )

    # Проверяем валидность ответа по матчу
    if not match_data or not match_data.get("match") or not match_data["match"].get("players"):
        logger.error(f"Не удалось получить полные данные для матча {match_id}")
        return None, None, None, None

    # Возвращаем все собранные данные
    return match_data, weekly_data, match_id, items_dict


async def handle_lastmatch(
    ctx: commands.Context, user_links_list: list[int], member: discord.Member | None = None
) -> None:
    """Основная логика команды /lastmatch.

    Получает данные о матче, форматирует их и отправляет в виде эмбеда.

    Args:
        ctx: Контекст команды Discord.
        user_links_list: Список Steam ID, привязанных к пользователю.
        member: Участник Discord, для которого запрашивается информация о матче.
               Если None, используется автор команды.
    """
    # Определяем ID пользователя Discord
    target_user = member if member else ctx.author
    user_id_str = str(target_user.id)  # Используем строковый ID для словаря
    target_user_mention = target_user.mention

    # Получаем ключ API Stratz из конфигурации бота
    stratz_key = ctx.bot.settings.stratz_api_key

    if not stratz_key:
        await ctx.send("Ошибка: STRATZ_API_KEY не найден в конфигурации бота.")
        logger.error("STRATZ_API_KEY не найден в конфигурации бота.")
        return

    # Проверяем, есть ли у пользователя привязанные Steam ID
    if not user_links_list:  # Проверяем переданный список
        message = (
            f"Пользователь {target_user_mention} не привязал свой аккаунт Dota 2."
            if member
            else "Сначала привяжите ваш аккаунт Discord к аккаунту Dota 2."
        )
        await ctx.send(f"{message} Используйте команду `/link PLAYER_ID`.")
        return

    # Создаем словарь в формате, который ожидает get_match_data
    user_links_dict = {user_id_str: user_links_list}

    # Вызываем функцию для получения данных о матче, недельной статистике и предметах
    match_data, weekly_data, match_id, items_dict = await get_match_data(
        user_links_dict, user_id_str, stratz_key
    )

    # Если данные о матче не получены
    if not match_data:
        await ctx.send(
            "Не удалось получить данные о последнем матче. "
            "Убедитесь, что история матчей доступна в настройках Dota 2, "
            "или попробуйте позже."
        )
        return

    # Извлекаем данные конкретного игрока из данных матча
    # (предполагается, что API возвращает только одного игрока при запросе с player_id)
    try:
        player_data = match_data["match"]["players"][0]
    except (IndexError, KeyError):
        logger.error(f"Некорректная структура данных игрока в ответе API для матча {match_id}")
        await ctx.send("Ошибка при обработке данных матча.")
        return

    # Извлекаем основную информацию о матче
    match_info = match_data.get("match", {})
    datetime_obj = datetime.fromtimestamp(match_info.get("startDateTime", 0), tz=UTC)
    duration = match_info.get("durationSeconds", 0)
    is_victory = player_data.get("isVictory", False)

    # Рассчитываем KDA
    kills = player_data.get("kills", 0)
    deaths = player_data.get("deaths", 0)
    assists = player_data.get("assists", 0)
    kda_value = (kills + assists) / max(
        deaths, 1
    )  # Делим на max(deaths, 1) чтобы избежать деления на ноль

    # Генерируем "остроумный" комментарий на основе KDA и результата матча
    if is_victory:
        kda_comment = (
            "красава разъебал"
            if kda_value > 4
            else "затащили дурака"
            if kda_value < 2
            else "норм сыграл"
        )
    else:
        kda_comment = (
            "старался, команда подвела"
            if kda_value > 4
            else "заруинил пидорас"
            if kda_value < 2
            else "норм сыграл"
        )

    # Цвет акцентной полосы контейнера: победа — зелёный, поражение — красный.
    accent = discord.Color.green() if is_victory else discord.Color.red()

    hero_name = player_data.get("hero", {}).get(
        "shortName", "unknown_hero"
    )  # shortName нужен для URL картинки героя
    game_mode = get_game_mode(match_info.get("gameMode", 0), match_info.get("lobbyType", None))
    role = get_role(player_data.get("position"))
    rank = convert_average_rank_to_medal(match_info.get("rank", 0))  # Средний ранг матча
    player_name = player_data.get("steamAccount", {}).get("name", "Неизвестно")

    networth = f"{player_data['networth']:,}" if player_data.get("networth") is not None else "N/A"
    hero_damage = (
        f"{player_data['heroDamage']:,}" if player_data.get("heroDamage") is not None else "N/A"
    )
    gpm = player_data.get("goldPerMinute", 0)
    xpm = player_data.get("experiencePerMinute", 0)

    # Дневной и недельный винрейт.
    daily_wl_str, weekly_wl_str = "N/A", "N/A"
    if weekly_data and weekly_data.get("player") and weekly_data["player"].get("matches"):
        matches_data = weekly_data["player"]["matches"]
        try:
            daily_wins, daily_losses, weekly_wins, weekly_losses = get_win_rates(matches_data)
            daily_wl_str = f"{daily_wins[0]}-{daily_losses[0]}"
            weekly_wl_str = f"{weekly_wins}-{weekly_losses}"
        except Exception as wl_error:
            logger.error(f"Ошибка при расчете винрейта: {wl_error}")

    # Предметы игрока (основные 6 слотов) + нейтралка выделена жирным.
    items_str = []
    if items_dict:
        for i in range(6):
            item_id = player_data.get(f"item{i}Id")
            if item_id and item_id > 0 and item_id in items_dict:
                items_str.append(items_dict[item_id].get("displayName", f"Item {item_id}"))
    neutral_str = ""
    if items_dict:
        neutral_id = player_data.get("neutral0Id")
        if neutral_id and neutral_id > 0 and neutral_id in items_dict:
            neutral_str = (
                " | **" + items_dict[neutral_id].get("displayName", f"Item {neutral_id}") + "**"
            )
    all_items = ", ".join(items_str) + neutral_str

    from config.settings import get_settings

    settings = get_settings()

    # Components V2: иерархия секций без эмодзи — шапка (вердикт + кто),
    # блок «Матч» (контекст игры), блок «Игрок» (KDA крупно + личная стата),
    # отдельный блок предметов и кнопки-ссылки.
    sep = "\u2002·\u2002"
    dur_str = f"{duration // 60}:{duration % 60:02}"
    date_str = datetime_obj.strftime("%d/%m/%Y")

    # Шапка: вердикт крупно + кто играл и на какой роли.
    header = f"### {kda_comment}\n**{player_name}**{sep}{role}"

    # Блок «Матч» — контекст игры, дата в подписи.
    match_block = f"-# МАТЧ{sep}{date_str}\n**{game_mode}**{sep}{dur_str}\nаверага **{rank}**"

    # Блок «Игрок» — KDA крупным числом + личная стата.
    player_block = (
        f"### {kda_value:.2f}\n"
        f"-# KDA\n"
        f"K/D/A **{kills}/{deaths}/{assists}**{sep}урон **{hero_damage}**\n"
        f"networth **{networth}**{sep}GPM/XPM **{gpm}/{xpm}**\n"
        f"W-L день **{daily_wl_str}**{sep}неделя **{weekly_wl_str}**"
    )

    items_block = f"-# ПРЕДМЕТЫ\n{all_items or 'нет данных'}"

    container: discord.ui.Container = discord.ui.Container(accent_colour=accent)
    container.add_item(
        discord.ui.Section(
            header,
            accessory=discord.ui.Thumbnail(
                f"https://cdn.stratz.com/images/dota2/heroes/{hero_name}_horz.png"
            ),
        )
    )
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(match_block))
    container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
    container.add_item(discord.ui.TextDisplay(player_block))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(items_block))
    container.add_item(
        discord.ui.ActionRow(
            Button(
                style=discord.ButtonStyle.link,
                label="Dotabuff",
                url=f"https://www.dotabuff.com/matches/{match_id}",
            ),
            Button(
                style=discord.ButtonStyle.link,
                label="OpenDota",
                url=f"https://opendota.com/matches/{match_id}",
            ),
            Button(
                style=discord.ButtonStyle.link,
                label="Stratz",
                url=f"https://stratz.com/matches/{match_id}",
            ),
        )
    )

    view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=settings.dota.match_view_timeout)
    view.add_item(container)
    await ctx.send(view=view)
