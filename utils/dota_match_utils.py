"""Утилиты для получения и отображения информации о матчах Dota 2.

Этот модуль предоставляет функции для запроса данных о последних матчах игроков Dota 2
через API Stratz, обработки полученной информации и отображения её в виде эмбедов Discord.
Включает GraphQL запросы, функции форматирования данных и создания интерактивных сообщений.
"""

import logging
from datetime import datetime
from typing import Optional, Tuple

import discord
from discord.ext import commands  # Для type hint в docstring
from discord.ui import Button, View

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
) -> Tuple[Optional[dict], Optional[dict], Optional[int], Optional[dict]]:
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

    # 1. Находим самый последний матч среди всех привязанных Steam ID пользователя
    latest_match = {"id": None, "startDateTime": 0}  # Храним ID и время последнего найденного матча
    latest_player_id = None  # Steam ID, которому принадлежит последний матч

    logger.debug(
        f"Поиск последнего матча для Discord ID {user_id} среди Steam ID: {user_links[user_id]}"
    )
    # Перебираем все привязанные Steam ID
    for player_id in user_links[user_id]:
        # Запрашиваем последний матч для текущего Steam ID (используем кэш)
        cache_key = f"matches_{player_id}_latest"
        response = await query_api_with_retry(
            QUERY_MATCHES, url, headers, {"player_id": player_id}, cache_key
        )

        # Проверяем валидность ответа и наличие матчей
        if response and response.get("player") and response["player"].get("matches"):
            match = response["player"]["matches"][0]  # Берем первый (последний) матч
            # Если этот матч новее, чем сохраненный `latest_match`, обновляем
            if match["startDateTime"] > latest_match["startDateTime"]:
                latest_match = match
                latest_player_id = player_id  # Запоминаем Steam ID этого матча
                logger.debug(f"Найден более новый матч {match['id']} для Steam ID {player_id}")

    # Если не найдено ни одного матча ни для одного Steam ID
    if latest_match["id"] is None:
        logger.warning(f"Не найдено матчей для пользователя {user_id}")
        return None, None, None, None

    logger.info(
        f"Последний матч для {user_id}: ID {latest_match['id']} (Steam ID: {latest_player_id})"
    )

    # 2. Получаем детальную информацию о найденном последнем матче
    match_id = latest_match["id"]
    cache_key = f"match_{match_id}_{latest_player_id}"
    match_data = await query_api_with_retry(
        QUERY_MATCH, url, headers, {"player_id": latest_player_id, "match_id": match_id}, cache_key
    )

    # Проверяем валидность ответа
    if not match_data or not match_data.get("match") or not match_data["match"].get("players"):
        logger.error(f"Не удалось получить полные данные для матча {match_id}")
        return None, None, None, None

    # 3. Получаем статистику матчей за последнюю неделю для расчета винрейта
    cache_key = f"matches_week_{latest_player_id}"
    weekly_data = await query_api_with_retry(
        QUERY_WEEKLY, url, headers, {"player_id": latest_player_id}, cache_key
    )

    # 4. Получаем данные о предметах (из кэша или API)
    items_dict = await fetch_items_data(url, headers)

    # Возвращаем все собранные данные
    return match_data, weekly_data, match_id, items_dict


async def handle_lastmatch(
    ctx: commands.Context, user_links_list: list[int], member: Optional[discord.Member] = None
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
    stratz_key = ctx.bot.config.get("STRATZ_API_KEY")

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
            (
                "Не удалось получить данные о последнем матче. "
                "Убедитесь, что история матчей доступна в настройках Dota 2, "
                "или попробуйте позже."
            )
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
    datetime_obj = datetime.utcfromtimestamp(match_info.get("startDateTime", 0))
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
            else "затащили дурака" if kda_value < 2 else "норм сыграл"
        )
    else:
        kda_comment = (
            "старался, команда подвела"
            if kda_value > 4
            else "заруинил пидорас" if kda_value < 2 else "норм сыграл"
        )

    # Определяем цвет эмбеда в зависимости от результата и KDA
    embed_color = (
        discord.Color.green()
        if is_victory and kda_value >= 3
        else (
            discord.Color.teal()
            if is_victory
            else discord.Color.red() if kda_value < 1.5 else discord.Color.gold()
        )
    )

    # Создаем основной эмбед для ответа
    embed = discord.Embed(title=f"**{kda_comment}**", color=embed_color)

    # Получаем и форматируем общие данные матча с помощью утилит
    hero_name = player_data.get("hero", {}).get(
        "shortName", "unknown_hero"
    )  # Используем shortName для URL картинки
    game_mode = get_game_mode(match_info.get("gameMode", 0), match_info.get("lobbyType", None))
    role = get_role(player_data.get("position"))
    rank = convert_average_rank_to_medal(match_info.get("rank", 0))  # Средний ранг матча

    # Заполняем поля эмбеда основной информацией
    player_name = player_data.get("steamAccount", {}).get("name", "Неизвестно")
    embed.add_field(name="Никнейм:", value=player_name, inline=True)
    embed.add_field(name="Роль:", value=role, inline=True)
    embed.add_field(name="KDA:", value=f"{kills}/{deaths}/{assists}", inline=True)

    embed.add_field(name="Режим:", value=game_mode, inline=True)
    embed.add_field(name="Длительность:", value=f"{duration // 60}:{duration % 60:02}", inline=True)
    embed.add_field(name="Аверага:", value=rank, inline=True)

    embed.add_field(
        name="GPM/XPM:",
        value=f"{player_data.get('goldPerMinute', 0)}/{player_data.get('experiencePerMinute', 0)}",
        inline=True,
    )
    embed.add_field(
        name="Networth:",
        value=f"{player_data.get('networth', 0):,}" if player_data.get("networth") else "N/A",
        inline=True,
    )
    embed.add_field(
        name="Hero Damage:",
        value=f"{player_data.get('heroDamage', 0):,}" if player_data.get("heroDamage") else "N/A",
        inline=True,
    )

    # Рассчитываем и форматируем дневной и недельный винрейт
    daily_wl_str, weekly_wl_str = "N/A", "N/A"  # Значения по умолчанию
    if weekly_data and weekly_data.get("player") and weekly_data["player"].get("matches"):
        matches_data = weekly_data["player"]["matches"]
        try:
            # get_win_rates может вызвать ошибку, если структура данных неверна
            daily_wins, daily_losses, weekly_wins, weekly_losses = get_win_rates(matches_data)
            daily_wl_str = f"{daily_wins[0]}-{daily_losses[0]}"  # Винрейт за последние 24 часа
            weekly_wl_str = f"{weekly_wins}-{weekly_losses}"  # Винрейт за последние 7 дней
        except Exception as wl_error:
            logger.error(f"Ошибка при расчете винрейта: {wl_error}")

    # Добавляем поля с датой и винрейтами
    embed.add_field(name="Дата:", value=datetime_obj.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="Daily W-L:", value=daily_wl_str, inline=True)
    embed.add_field(name="Weekly W-L:", value=weekly_wl_str, inline=True)

    # Формируем строку с предметами игрока (основные 6 слотов)
    items_str = []
    if items_dict:  # Проверяем, что словарь предметов загружен
        for i in range(6):
            item_id = player_data.get(f"item{i}Id")  # ID предмета из слота i
            # Ищем предмет в словаре items_dict и добавляем его displayName
            if item_id and item_id > 0 and item_id in items_dict:
                items_str.append(items_dict[item_id].get("displayName", f"Item {item_id}"))

    # Добавляем нейтральный предмет (если есть)
    neutral_str = ""
    if items_dict:  # Проверяем, что словарь предметов загружен
        neutral_id = player_data.get("neutral0Id")
        if neutral_id and neutral_id > 0 and neutral_id in items_dict:
            neutral_str = (
                " | **" + items_dict[neutral_id].get("displayName", f"Item {neutral_id}") + "**"
            )  # Выделяем нейтралку

    # Объединяем основные и нейтральный предметы
    all_items = ", ".join(items_str) + neutral_str
    embed.add_field(name="Предметы:", value=all_items or "Нет данных", inline=False)

    # Устанавливаем иконку героя как thumbnail эмбеда
    embed.set_thumbnail(url=f"https://cdn.stratz.com/images/dota2/heroes/{hero_name}_horz.png")
    # Устанавливаем автора эмбеда (ник и аватар игрока)
    player_avatar = player_data.get("steamAccount", {}).get("avatar")
    if player_avatar:
        embed.set_author(name=player_name, icon_url=player_avatar)
    else:
        embed.set_author(name=player_name)  # Если аватара нет, ставим только имя

    # Получаем настройки
    from config.settings import get_settings

    settings = get_settings()

    # Создаем View с кнопками-ссылками на внешние ресурсы
    view = View(timeout=settings.dota.match_view_timeout)  # Таймаут из настроек
    view.add_item(
        Button(
            style=discord.ButtonStyle.link,
            label="Dotabuff",
            url=f"https://www.dotabuff.com/matches/{match_id}",
        )
    )
    view.add_item(
        Button(
            style=discord.ButtonStyle.link,
            label="OpenDota",
            url=f"https://opendota.com/matches/{match_id}",
        )
    )
    view.add_item(
        Button(
            style=discord.ButtonStyle.link,
            label="Stratz",
            url=f"https://stratz.com/matches/{match_id}",
        )
    )

    # Отправляем финальное сообщение с эмбедом и кнопками
    await ctx.send(embed=embed, view=view)
