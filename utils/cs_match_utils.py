"""Утилиты для получения и отображения информации о матчах CS2 через FACEIT.

Модуль зеркалит :mod:`utils.dota_match_utils`: ищет последний матч игрока среди
привязанных аккаунтов FACEIT, тянет детали матча и статистику игрока, считает
recent W-L и рисует тот же Components V2 контейнер, что и Dota-команда.
"""

import asyncio
import logging
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import discord
from discord.ext import commands

from utils.cs_api import faceit_get_with_retry
from utils.cs_links_data_manager import CsLink
from utils.match_card import CsCardData, fetch_image_bytes, load_map_image, render_cs_card
from utils.ui import image_card

logger = logging.getLogger("bot.utils.cs_match_utils")


async def resolve_player_by_nickname(nickname: str, api_key: str) -> dict[str, Any] | None:
    """Резолвит ник FACEIT в данные игрока (включая ``player_id`` и CS2-профиль).

    Args:
        nickname: Ник игрока на FACEIT.
        api_key: Ключ FACEIT Data API.

    Returns:
        Словарь с данными игрока или None, если игрок не найден / нет данных CS2.
    """
    data = await faceit_get_with_retry(
        "/players",
        api_key,
        params={"nickname": nickname},
        cache_key=f"faceit_player_nick_{nickname.lower()}",
        ttl=300,
    )
    if not data or not data.get("player_id"):
        return None
    if "cs2" not in (data.get("games") or {}):
        return None
    return data


def _player_faction(item: dict[str, Any], player_id: str) -> str | None:
    """Определяет, за какую фракцию (faction1/faction2) играл игрок в матче истории."""
    teams = item.get("teams", {})
    for faction in ("faction1", "faction2"):
        players = teams.get(faction, {}).get("players", [])
        if any(p.get("player_id") == player_id for p in players):
            return faction
    return None


def _item_is_win(item: dict[str, Any], player_id: str) -> bool | None:
    """Возвращает True/False — победил ли игрок в матче истории, или None если неясно."""
    faction = _player_faction(item, player_id)
    if faction is None:
        return None
    winner = item.get("results", {}).get("winner")
    if not winner:
        return None
    return bool(faction == winner)


def _compute_lobby_avg_level(item: dict[str, Any]) -> float | None:
    """Считает средний FACEIT-уровень лобби по ростеру матча из истории.

    Элемент истории уже содержит ``skill_level`` каждого игрока обеих команд,
    поэтому среднее по лобби берётся без дополнительных запросов к API.

    Args:
        item: Элемент ответа /players/{id}/history.

    Returns:
        Средний уровень (округлён до 1 знака) или None, если уровней нет.
    """
    teams = item.get("teams", {})
    levels: list[int] = []
    for faction in ("faction1", "faction2"):
        for player in teams.get(faction, {}).get("players", []):
            lvl = _to_int(player.get("skill_level", player.get("game_skill_level")))
            if lvl > 0:
                levels.append(lvl)
    if not levels:
        return None
    return round(sum(levels) / len(levels), 1)


def _compute_recent_wl(items: list[dict[str, Any]], player_id: str) -> tuple[int, int]:
    """Считает recent W-L по списку матчей истории."""
    wins = 0
    losses = 0
    for item in items:
        result = _item_is_win(item, player_id)
        if result is True:
            wins += 1
        elif result is False:
            losses += 1
    return wins, losses


def _compute_recent_results(items: list[dict[str, Any]], player_id: str) -> list[bool]:
    """Упорядоченная (свежие первыми) последовательность исходов для плиток W/L.

    Матчи с неопределённым результатом пропускаются — в ряд идут только явные W/L.
    """
    results: list[bool] = []
    for item in items:
        outcome = _item_is_win(item, player_id)
        if outcome is not None:
            results.append(outcome)
    return results


def _extract_match_stats(
    stats: dict[str, Any], player_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """Извлекает из ответа /matches/{id}/stats данные первой карты для игрока.

    Returns:
        Кортеж (round_stats, player_stats, player_team, other_team) или None.
    """
    rounds = stats.get("rounds") or []
    if not rounds:
        return None
    rnd = rounds[0]
    round_stats = rnd.get("round_stats", {})
    teams = rnd.get("teams", [])

    player_stats: dict[str, Any] | None = None
    player_team: dict[str, Any] | None = None
    other_team: dict[str, Any] | None = None

    for team in teams:
        players = team.get("players", [])
        match = next((p for p in players if p.get("player_id") == player_id), None)
        if match is not None:
            player_team = team
            player_stats = match.get("player_stats", {})
        else:
            other_team = team

    if player_stats is None or player_team is None or other_team is None:
        return None
    return round_stats, player_stats, player_team, other_team


async def get_cs_match_data(
    player_ids: list[str], api_key: str, recent_count: int
) -> dict[str, Any] | None:
    """Получает данные о последнем матче CS2 среди привязанных аккаунтов FACEIT.

    Находит самый свежий матч (по ``finished_at``) среди всех ``player_ids``,
    затем параллельно тянет статистику матча и профиль игрока.

    Args:
        player_ids: Список FACEIT player_id пользователя.
        api_key: Ключ FACEIT Data API.
        recent_count: Сколько последних матчей брать для recent W-L.

    Returns:
        Словарь с ключами ``item``, ``stats``, ``player``, ``recent_wl``,
        ``player_id`` или None при ошибке/отсутствии матчей.
    """
    if not player_ids:
        return None

    histories = await asyncio.gather(
        *(
            faceit_get_with_retry(
                f"/players/{pid}/history",
                api_key,
                params={"game": "cs2", "offset": 0, "limit": recent_count},
                cache_key=f"faceit_history_{pid}_{recent_count}",
                ttl=60,
            )
            for pid in player_ids
        ),
        return_exceptions=True,
    )

    latest_item: dict[str, Any] | None = None
    latest_items: list[dict[str, Any]] = []
    latest_player_id: str | None = None
    latest_ts = -1

    for pid, history in zip(player_ids, histories, strict=True):
        if isinstance(history, BaseException):
            logger.warning("Ошибка при запросе истории FACEIT для %s: %s", pid, history)
            continue
        if not history:
            continue
        items = history.get("items") or []
        if not items:
            continue
        first = items[0]
        ts = first.get("finished_at", 0) or 0
        if ts > latest_ts:
            latest_ts = ts
            latest_item = first
            latest_items = items
            latest_player_id = pid

    if latest_item is None or latest_player_id is None:
        logger.warning("Не найдено матчей FACEIT для player_ids: %s", player_ids)
        return None

    match_id = latest_item.get("match_id")
    if not match_id:
        return None

    stats, player = await asyncio.gather(
        faceit_get_with_retry(
            f"/matches/{match_id}/stats",
            api_key,
            cache_key=f"faceit_match_stats_{match_id}",
            ttl=3600,
        ),
        faceit_get_with_retry(
            f"/players/{latest_player_id}",
            api_key,
            cache_key=f"faceit_player_{latest_player_id}",
            ttl=300,
        ),
    )

    if not stats:
        logger.error("Не удалось получить статистику матча FACEIT %s", match_id)
        return None

    recent_wl = _compute_recent_wl(latest_items, latest_player_id)
    recent_results = _compute_recent_results(latest_items, latest_player_id)

    return {
        "item": latest_item,
        "stats": stats,
        "player": player,
        "recent_wl": recent_wl,
        "recent_results": recent_results,
        "player_id": latest_player_id,
    }


def _to_int(value: Any, default: int = 0) -> int:
    """Безопасно приводит строковое значение FACEIT к int."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    """Безопасно приводит строковое значение FACEIT к float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# Средние по лиге значения из reverse-engineered формулы HLTV 1.0
# (kills/round, survived/round, weighted-multikills/round).
_HLTV_AVG_KPR = 0.679
_HLTV_AVG_SPR = 0.317
_HLTV_AVG_RMK = 1.277


def _compute_hltv1_rating(player_stats: dict[str, Any], rounds: int) -> float | None:
    """Считает приближённый HLTV 1.0 rating из сырых статов FACEIT.

    FACEIT не отдаёт готовый Rating/Swing через Data API, поэтому считаем его сами
    по общепринятой формуле ``(KillRating + 0.7*SurvivalRating + MultiKillRating) /
    2.7``. HLTV 2.x недоступна (нужен KAST, которого в API нет), так что число
    близкое к рейтингу из комнаты FACEIT, но не совпадает с ним точь-в-точь.

    Args:
        player_stats: Карта статов игрока за карту (``Kills``, ``Deaths`` и т.д.).
        rounds: Сыграно раундов на карте.

    Returns:
        Рейтинг, округлённый до 2 знаков, или None если число раундов неизвестно.
    """
    if rounds <= 0:
        return None

    kills = _to_int(player_stats.get("Kills"))
    deaths = _to_int(player_stats.get("Deaths"))
    k2 = _to_int(player_stats.get("Double Kills"))
    k3 = _to_int(player_stats.get("Triple Kills"))
    k4 = _to_int(player_stats.get("Quadro Kills"))
    k5 = _to_int(player_stats.get("Penta Kills"))
    # Одиночные килы выводим из общего числа, вычтя мультикилы.
    k1 = max(0, kills - 2 * k2 - 3 * k3 - 4 * k4 - 5 * k5)

    kill_rating = (kills / rounds) / _HLTV_AVG_KPR
    survival_rating = ((rounds - deaths) / rounds) / _HLTV_AVG_SPR
    multikill_rating = (k1 + 4 * k2 + 9 * k3 + 16 * k4 + 25 * k5) / rounds / _HLTV_AVG_RMK

    rating = (kill_rating + 0.7 * survival_rating + multikill_rating) / 2.7
    return round(rating, 2)


async def handle_cs_lastmatch(
    ctx: commands.Context,
    links: list[CsLink],
    member: discord.Member | None = None,
) -> None:
    """Основная логика команды /cslastmatch.

    Получает данные о последнем матче CS2, форматирует их и отправляет в виде
    Components V2 контейнера.

    Args:
        ctx: Контекст команды Discord.
        links: Список CS-привязок пользователя.
        member: Участник Discord, для которого запрашивается матч (или автор).
    """
    target_user = member if member else ctx.author
    target_mention = target_user.mention

    api_key = ctx.bot.settings.faceit_api_key
    if not api_key:
        await ctx.send("Ошибка: FACEIT_API_KEY не найден в конфигурации бота.")
        logger.error("FACEIT_API_KEY не найден в конфигурации бота.")
        return

    if not links:
        message = (
            f"Пользователь {target_mention} не привязал аккаунт FACEIT."
            if member
            else "Сначала привяжите аккаунт FACEIT."
        )
        await ctx.send(f"{message} Используйте команду `/cslink <ник>`.")
        return

    recent_count = ctx.bot.settings.cs.recent_matches_count
    player_ids = [link.faceit_player_id for link in links]

    data = await get_cs_match_data(player_ids, api_key, recent_count)
    if not data:
        await ctx.send(
            "Не удалось получить данные о последнем матче CS2. "
            "Возможно, статистика ещё не готова — попробуйте чуть позже."
        )
        return

    extracted = _extract_match_stats(data["stats"], data["player_id"])
    if extracted is None:
        logger.error("Не удалось извлечь статистику игрока из матча FACEIT")
        await ctx.send("Ошибка при обработке данных матча.")
        return

    round_stats, player_stats, player_team, other_team = extracted
    item = data["item"]
    player = data["player"] or {}

    kills = _to_int(player_stats.get("Kills"))
    deaths = _to_int(player_stats.get("Deaths"))
    assists = _to_int(player_stats.get("Assists"))
    kd_ratio = _to_float(player_stats.get("K/D Ratio"))
    adr = player_stats.get("ADR")
    hs_percent = _to_int(player_stats.get("Headshots %"))
    mvps = _to_int(player_stats.get("MVPs"))

    # FACEIT advanced-статы: показываем «—», если поля нет в ответе, чтобы не
    # выдавать отсутствие данных за честный ноль.
    entry_count = player_stats.get("Entry Count")
    entry_wins = player_stats.get("Entry Wins")
    entry_str = f"{_to_int(entry_wins)}/{_to_int(entry_count)}" if entry_count is not None else "—"

    clutch_vals = [player_stats.get(f"1v{n}Wins") for n in range(1, 6)]
    clutch_str = (
        str(sum(_to_int(v) for v in clutch_vals))
        if any(v is not None for v in clutch_vals)
        else "—"
    )

    util_dmg = player_stats.get("Utility Damage")
    util_str = str(_to_int(util_dmg)) if util_dmg is not None else "—"

    is_victory = str(player_team.get("team_stats", {}).get("Team Win")) == "1"
    player_score = _to_int(player_team.get("team_stats", {}).get("Final Score"))
    opp_score = _to_int(other_team.get("team_stats", {}).get("Final Score"))

    rounds_played = _to_int(round_stats.get("Rounds")) or (player_score + opp_score)
    rating = _compute_hltv1_rating(player_stats, rounds_played)

    # По рейтингу комментарий точнее, чем по голому K/D; если рейтинг посчитать
    # не удалось — откатываемся на старый критерий по K/D.
    if rating is not None:
        score_metric, good, bad = rating, 1.15, 0.85
    else:
        score_metric, good, bad = kd_ratio, 1.5, 0.8

    if is_victory:
        kda_comment = (
            "красава разъебал"
            if score_metric > good
            else "затащили дурака"
            if score_metric < bad
            else "норм сыграл"
        )
    else:
        kda_comment = (
            "старался, команда подвела"
            if score_metric > good
            else "заруинил пидорас"
            if score_metric < bad
            else "норм сыграл"
        )

    accent = discord.Color.green() if is_victory else discord.Color.red()

    map_name = str(round_stats.get("Map", "")).removeprefix("de_") or "unknown"
    nickname = player.get("nickname") or links[0].nickname
    avatar = player.get("avatar") or ""

    cs2_profile = (player.get("games") or {}).get("cs2", {})
    elo = cs2_profile.get("faceit_elo")
    level = cs2_profile.get("skill_level")
    elo_str = str(elo) if elo is not None else "N/A"
    level_str = str(level) if level is not None else "N/A"

    wins, losses = data["recent_wl"]
    recent_results = data["recent_results"]

    finished_at = item.get("finished_at", 0) or 0
    started_at = item.get("started_at", 0) or 0
    datetime_obj = datetime.fromtimestamp(finished_at, tz=UTC)
    date_str = datetime_obj.strftime("%d/%m/%Y")
    duration = max(0, finished_at - started_at)
    dur_str = f"{duration // 60}:{duration % 60:02}" if duration else "N/A"

    adr_str = f"{_to_float(adr):.0f}" if adr is not None else "N/A"
    rating_str = f"{rating:.2f}" if rating is not None else "N/A"
    kr_str = f"{kills / rounds_played:.2f}" if rounds_played else "N/A"
    avg_lvl = _compute_lobby_avg_level(item)

    from config.settings import get_settings

    settings = get_settings()

    card = CsCardData(
        verdict=kda_comment,
        is_victory=is_victory,
        nickname=nickname,
        level=level_str,
        elo=elo_str,
        player_score=player_score,
        opp_score=opp_score,
        rating_str=rating_str,
        rating_is_good=rating is not None and score_metric > good,
        kda_str=f"{kills}/{deaths}/{assists}",
        kd_str=f"{kd_ratio:.2f}",
        adr_str=adr_str,
        hs_percent=hs_percent,
        kr_str=kr_str,
        mvp_str=str(mvps),
        entry_str=entry_str,
        clutch_str=clutch_str,
        util_str=util_str,
        recent_wins=wins,
        recent_losses=losses,
        recent_results=recent_results,
        date_str=date_str,
        duration_str=dur_str,
        avg_lobby_lvl=f"{avg_lvl:.1f}" if avg_lvl is not None else None,
        avatar=await fetch_image_bytes(avatar),
        map_bg=load_map_image(map_name),
    )
    png = await asyncio.to_thread(render_cs_card, card)
    file = discord.File(BytesIO(png), filename="cs_match.png")

    faceit_url = str(item.get("faceit_url", "")).replace("{lang}", "en")
    match_links: list[tuple[str, str]] = []
    if faceit_url:
        match_links.append(("FACEIT матч", faceit_url))
    match_links.append(("Профиль", f"https://www.faceit.com/en/players/{nickname}"))

    # PNG вставляем в Components V2 через attachment:// — контейнер сохраняет
    # accent-полосу (зелёная/красная) и кнопки-ссылки в одном сообщении.
    view = image_card(
        media="attachment://cs_match.png",
        accent=accent,
        links=match_links,
        timeout=settings.cs.match_view_timeout,
    )
    await ctx.send(view=view, file=file)
