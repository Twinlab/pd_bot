"""Модуль для генерации и отправки отчетов об игровой активности пользователей.

Содержит функции для формирования и отправки ежедневных и ежемесячных отчетов
об игровой активности пользователей в указанный канал Discord.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import discord

from utils.activity_data_manager import ActivityDataManager
from utils.scheduled_delivery import ScheduledDelivery
from utils.time_utils import MOSCOW_TZ

from .helpers import format_time_short
from .views import ActivityView

if TYPE_CHECKING:
    from cogs.activity import ActivityTracker

logger = logging.getLogger("bot.utils.activity")

# Словарь для названий месяцев
MONTH_NAMES_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


async def _get_report_channel(bot: discord.Client) -> discord.TextChannel | None:
    """Находит и возвращает канал для отправки отчетов из ``bot.settings``.

    Args:
        bot: Экземпляр бота Discord (ожидается атрибут ``settings``).

    Returns:
        Объект discord.TextChannel или None, если канал не найден.
    """
    settings = getattr(bot, "settings", None)
    if settings is None:
        logger.error("У бота нет атрибута settings — не могу определить канал для отчётов.")
        return None

    report_channel_id = settings.channels.activity_reports
    channel = bot.get_channel(report_channel_id)
    if not channel:
        logger.error(f"Канал для отчетов (ID: {report_channel_id}) не найден.")
        return None
    if not isinstance(channel, discord.TextChannel):
        logger.error(f"Канал для отчетов (ID: {report_channel_id}) не является текстовым каналом.")
        return None
    return channel


async def _send_report_part(
    bot: discord.Client, channel: discord.TextChannel, part: dict[str, Any]
) -> discord.Message:
    if part.get("kind") == "daily":
        data = {int(uid): games for uid, games in part["data"].items()}
        view = ActivityView(bot, data, report_type="daily", date_str=f" ({part['date']})")
        message = await channel.send(
            content=view.get_current_content(),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        view.message = message
        return message
    return await channel.send(part["content"], allowed_mentions=discord.AllowedMentions.none())


def _matches_report_part(part: dict[str, Any], message: discord.Message) -> bool:
    if part.get("kind") == "daily":
        return message.content.startswith(
            f"# 📊 Ежедневный отчет игровой активности ({part['date']})\n"
        )
    return bool(message.content == part["content"])


async def send_daily_report(
    target_date: date,
    bot: discord.Client,
    data_manager: ActivityDataManager,
    channel: discord.TextChannel | None = None,
    *,
    delivery: ScheduledDelivery | None = None,
) -> bool:
    """Отправляет дневную статистику; автоматическая доставка сохраняет снимок.

    Args:
        target_date: Московская дата отчёта.
        bot: Бот с настройками и участниками сервера.
        data_manager: Источник статистики.
        channel: Канал; по умолчанию канал отчётов.
        delivery: Журнал автоматических публикаций или None для ручного запроса.

    Returns:
        True после полной доставки, False при ошибке или неопределённом результате.
    """
    channel = channel or await _get_report_channel(bot)
    if channel is None:
        return False

    async def prepare() -> list[dict[str, Any]]:
        data = await data_manager.get_daily_stats(target_date, strict=True)
        if not data:
            return [{"content": f"За {target_date:%d.%m.%Y} никто не играл в игры 😢"}]
        return [{"kind": "daily", "date": f"{target_date:%d.%m.%Y}", "data": data}]

    async def send(part: dict[str, Any]) -> discord.Message:
        return await _send_report_part(bot, channel, part)

    try:
        if delivery is not None:
            if bot.user is None:
                return False
            result = await delivery.deliver(
                f"daily:{target_date}",
                channel=channel,
                bot_id=bot.user.id,
                prepare=prepare,
                send=send,
                matches=_matches_report_part,
            )
            return result is not None
        for part in await prepare():
            await send(part)
        return True
    except Exception:
        logger.exception("Не удалось доставить дневной отчёт за %s", target_date)
        if delivery is None:
            try:
                await channel.send(
                    f"Не удалось сформировать ежедневный отчет за {target_date:%d.%m.%Y}. Попробуйте позже или обратитесь к администратору."
                )
            except Exception:
                logger.warning("Канал дневного отчёта недоступен")
        return False


def _get_monthly_summary_text(data: dict[int, dict[str, int]], month: int, year: int) -> str:
    """Формирует текстовую сводку для ежемесячного отчета.

    Использует краткий формат времени.

    Args:
        data: Словарь с данными активности {user_id: {game_name: seconds}}.
        month: Номер месяца.
        year: Год.

    Returns:
        Строка с общей статистикой за месяц.
    """
    total_users = len(data)
    all_games: dict[str, dict[str, Any]] = defaultdict(lambda: {"players": 0, "time": 0})
    total_time_all_games = 0

    for user_data in data.values():
        for game, time_spent in user_data.items():
            if time_spent > 0:
                all_games[game]["players"] += 1
                all_games[game]["time"] += time_spent
                total_time_all_games += time_spent

    total_unique_games = len(all_games)

    most_popular_game_name: str | None = None
    max_players = 0
    most_time_game_name: str | None = None
    max_time = 0

    for game, stats in all_games.items():
        if stats["players"] > max_players:
            max_players = stats["players"]
            most_popular_game_name = game
        if stats["time"] > max_time:
            max_time = stats["time"]
            most_time_game_name = game

    month_str = MONTH_NAMES_RU.get(month, str(month))
    summary = f"## 📊 Общая статистика за {month_str} {year}\n"
    summary += f"👥 Всего активных игроков: **{total_users}**\n"
    summary += f"🎮 Уникальных игр: **{total_unique_games}**\n"
    summary += (
        "⏱️ Общее время в играх: **" + format_time_short(total_time_all_games) + "**\n\n"
    )  # Краткий формат времени

    if most_popular_game_name:
        players_str = (
            f"{max_players} {'игрока' if 2 <= max_players <= 4 else 'игроков'}"
            if max_players > 1
            else "1 игрок"
        )
        summary += f"🏆 Самая популярная игра: **{most_popular_game_name}** ({players_str})\n"
    if most_time_game_name and most_time_game_name != most_popular_game_name:
        # Показываем игру с наибольшим временем, только если она не совпадает с самой популярной
        summary += (
            f"⭐ Игра с наибольшим временем: **{most_time_game_name}** "
            f"({format_time_short(max_time)})\n"
        )  # Краткий формат времени

    return summary


def _monthly_parts(
    bot: discord.Client,
    channel: discord.TextChannel,
    data: dict[int, dict[str, int]],
    year: int,
    month: int,
) -> list[str]:
    month_name = MONTH_NAMES_RU[month]
    if not data:
        return [f"Нет данных об активности за {month_name} {year} 😢"]
    settings = getattr(bot, "settings", None)
    threshold = settings.timeouts.activity_monthly_min_time if settings is not None else 1800
    users = []
    for user_id, activities in data.items():
        member = channel.guild.get_member(user_id)
        name = member.name if member else f"Пользователь {user_id}"
        games = {game: seconds for game, seconds in activities.items() if seconds >= threshold}
        users.append((name, games, sum(activities.values())))
    lines = []
    for name, games, total in sorted(users, key=lambda row: row[0].lower()):
        listed = ", ".join(
            f"{game} ({format_time_short(seconds)})"
            for game, seconds in sorted(games.items(), key=lambda item: item[1], reverse=True)
        )
        lines.append(f"**{name}** (*{format_time_short(total)}*): {listed}\n")
    top = "## 🏆 Топ-3 игрока по игровому времени\n" + "".join(
        f"{index}. **{name}** (*{format_time_short(total)}*)\n"
        for index, (name, _, total) in enumerate(
            sorted(users, key=lambda row: row[2], reverse=True)[:3], 1
        )
    )
    summary = _get_monthly_summary_text(data, month, year)
    header = f"# 📊 Ежемесячный отчет за {month_name} {year}\n\n"
    section = "## 👤 Активность всех пользователей\n*(Показаны только игры с временем более 30 минут)*\n\n"
    complete = header + section + "".join(lines) + top + summary
    if len(complete) <= 1900:
        return [complete]
    chunks = [header, section]
    buffer = ""
    for line in [*lines, top, summary]:
        while len(line) > 1900:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.append(line[:1900])
            line = line[1900:]
        if len(buffer) + len(line) > 1900:
            chunks.append(buffer)
            buffer = ""
        buffer += line
    if buffer:
        chunks.append(buffer)
    return chunks


async def send_monthly_report(
    year: int,
    month: int,
    bot: discord.Client,
    data_manager: ActivityDataManager,
    channel: discord.TextChannel | None = None,
    *,
    delivery: ScheduledDelivery | None = None,
) -> bool:
    """Отправляет месячный отчёт, сохраняя прогресс каждой части при автоматической доставке.

    Args:
        year: Год отчёта.
        month: Месяц отчёта.
        bot: Бот с настройками и участниками сервера.
        data_manager: Источник статистики.
        channel: Канал; по умолчанию канал отчётов.
        delivery: Журнал автоматических публикаций или None для ручного запроса.

    Returns:
        True после полной доставки, False при ошибке или ожидании проверки истории.
    """
    channel = channel or await _get_report_channel(bot)
    if channel is None:
        return False

    async def prepare() -> list[dict[str, Any]]:
        data = await data_manager.get_aggregated_monthly_stats(
            year, month, strict=True, include_pending=True
        )
        chunks = _monthly_parts(bot, channel, data, year, month)
        return [
            {
                "content": (
                    f"-# {MONTH_NAMES_RU[month]} {year} · часть {index}/{len(chunks)}\n"
                    if delivery and len(chunks) > 1
                    else ""
                )
                + chunk
            }
            for index, chunk in enumerate(chunks, 1)
        ]

    async def send(part: dict[str, Any]) -> discord.Message:
        return await _send_report_part(bot, channel, part)

    try:
        if delivery is not None:
            if bot.user is None:
                return False
            result = await delivery.deliver(
                f"monthly:{year}-{month:02d}",
                channel=channel,
                bot_id=bot.user.id,
                prepare=prepare,
                send=send,
                matches=_matches_report_part,
            )
            return result is not None
        for part in await prepare():
            await send(part)
        return True
    except Exception:
        logger.exception("Не удалось доставить месячный отчёт за %s-%02d", year, month)
        if delivery is None:
            try:
                await channel.send(
                    f"Не удалось сформировать ежемесячный отчет за {MONTH_NAMES_RU.get(month, month)} {year}. Попробуйте позже."
                )
            except Exception:
                logger.warning("Канал месячного отчёта недоступен")
        return False


async def run_automatic_daily_report(
    cog_instance: "ActivityTracker", *, flush: bool = True
) -> None:
    """Доставляет новые и недоставленные дни, затем переносит их в месячные итоги."""
    try:
        today = datetime.now(MOSCOW_TZ).date()
        yesterday = today - timedelta(days=1)
        manager = cog_instance.data_manager
        delivery = getattr(cog_instance, "report_delivery", None)
        first_day = (
            (await delivery.activation_time()).astimezone(MOSCOW_TZ).date()
            if delivery
            else yesterday
        )
        if flush:
            await cog_instance.update_current_activities()
        pending = await delivery.pending_keys("daily:") if delivery else []
        dates = sorted(
            {
                yesterday,
                *await manager.get_pending_daily_dates(today),
                *(date.fromisoformat(key.removeprefix("daily:")) for key in pending),
            }
        )
        for target in dates:
            if target >= first_day:
                sent = await send_daily_report(target, cog_instance.bot, manager, delivery=delivery)
                if not sent:
                    logger.warning(
                        "Отчёт за %s не доставлен; дневные данные сохранены для повтора", target
                    )
                    continue
            if not await manager.transfer_daily_to_monthly(target):
                logger.error("Не удалось архивировать дневную статистику за %s", target)
    except Exception:
        logger.exception("Не удалось обработать автоматические дневные отчёты")


async def run_automatic_monthly_report(cog_instance: "ActivityTracker") -> None:
    """Догоняет месячную публикацию после пропущенного запуска первого числа."""
    try:
        now = datetime.now(MOSCOW_TZ)
        due = now.replace(day=1, hour=12, minute=0, second=0, microsecond=0)
        delivery = getattr(cog_instance, "report_delivery", None)
        periods: set[tuple[int, int]] = set()
        if delivery:
            for key in await delivery.pending_keys("monthly:"):
                period = date.fromisoformat(key.removeprefix("monthly:") + "-01")
                periods.add((period.year, period.month))
            due_now = (await delivery.activation_time()) <= due <= now
        else:
            due_now = now.day == 1
        if due_now:
            previous = now.date().replace(day=1) - timedelta(days=1)
            periods.add((previous.year, previous.month))
        for year, month in sorted(periods):
            await send_monthly_report(
                year,
                month,
                cog_instance.bot,
                cog_instance.data_manager,
                delivery=delivery,
            )
    except Exception:
        logger.exception("Не удалось обработать автоматический месячный отчёт")
