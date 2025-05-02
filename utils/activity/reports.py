import discord
import asyncio
import logging
import pytz
from datetime import date, timedelta, datetime
from collections import defaultdict
from typing import Dict, Any, Optional

# Импортируем необходимые компоненты
from utils.activity_data_manager import ActivityDataManager
from .views import ActivityView
from .helpers import format_time_short # Импортируем только краткий формат времени

# Логгер для этого модуля
# Используем иерархическое имя в соответствии с README
logger = logging.getLogger("bot.activity.reports")

# Словарь для названий месяцев
MONTH_NAMES_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}

async def _get_report_channel(bot: discord.Client, config: Dict[str, Any]) -> Optional[discord.TextChannel]:
    """
    Находит и возвращает канал для отправки отчетов.

    Args:
        bot: Экземпляр бота Discord.
        config: Словарь конфигурации бота (для получения ID канала).

    Returns:
        Объект discord.TextChannel или None, если канал не найден.
    """
    # ID канала по умолчанию, если не найден в конфиге
    default_channel_id = 573665353327181824
    report_channel_id = config.get("REPORT_CHANNEL_ID", default_channel_id)
    channel = bot.get_channel(report_channel_id)
    if not channel:
        logger.error(f"Канал для отчетов (ID: {report_channel_id}) не найден.")
        return None
    if not isinstance(channel, discord.TextChannel):
        logger.error(f"Канал для отчетов (ID: {report_channel_id}) не является текстовым каналом.")
        return None
    return channel

async def send_daily_report(
    target_date: date,
    bot: discord.Client,
    data_manager: ActivityDataManager,
    config: Dict[str, Any],
    channel: Optional[discord.TextChannel] = None
) -> bool:
    """
    Получает данные за указанную дату и отправляет ежедневный отчет в виде ActivityView.

    Args:
        target_date: Дата, за которую нужно отправить отчет.
        bot: Экземпляр бота Discord.
        data_manager: Экземпляр ActivityDataManager.
        config: Словарь конфигурации бота.
        channel: Канал для отправки отчета. Если None, будет использован канал из конфигурации.

    Returns:
        True, если отчет успешно отправлен (или данных не было), False при ошибке.
    """
    logger.info(f"Запрос на отправку ежедневного отчета за {target_date.isoformat()}")
    
    # Если канал не указан, получаем его из конфигурации
    if channel is None:
        channel = await _get_report_channel(bot, config)
        if not channel:
            return False # Ошибка уже залогирована в _get_report_channel

    try:
        daily_data = await data_manager.get_daily_stats(target_date)

        if not daily_data:
            await channel.send(f"За {target_date.strftime('%d.%m.%Y')} никто не играл в игры 😢")
            logger.info(f"Отправлено уведомление об отсутствии данных для ежедневного отчета за {target_date.isoformat()}.")
            return True # Считаем успехом, т.к. обработали случай отсутствия данных
        else:
            # Форматируем дату для отображения в отчете
            formatted_date = target_date.strftime("%d.%m.%Y")
            # Используем ActivityView для интерактивного отчета
            view = ActivityView(bot, daily_data, report_type="daily", date_str=f" ({formatted_date})")
            message = await channel.send(content=view.get_current_content(), view=view)
            view.message = message # Сохраняем сообщение для возможности отключения кнопок по таймауту
            logger.info(f"Отправлен ежедневный отчет за {target_date.isoformat()}")
            return True
    except Exception as e:
        logger.error(f"Ошибка при получении данных или отправке ежедневного отчета за {target_date.isoformat()}: {e}", exc_info=True)
        try:
            # Попытка уведомить об ошибке в тот же канал
            await channel.send(f"Не удалось сформировать ежедневный отчет за {target_date.strftime('%d.%m.%Y')}. Ошибка: {e}")
        except Exception as send_e:
            logger.error(f"Не удалось отправить сообщение об ошибке генерации ежедневного отчета: {send_e}")
        return False

def _get_monthly_summary_text(data: Dict[int, Dict[str, int]], month: int, year: int) -> str:
    """
    Формирует текстовую сводку для ежемесячного отчета.
    Использует краткий формат времени.

    Args:
        data: Словарь с данными активности {user_id: {game_name: seconds}}.
        month: Номер месяца.
        year: Год.

    Returns:
        Строка с общей статистикой за месяц.
    """
    total_users = len(data)
    all_games: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"players": 0, "time": 0})
    total_time_all_games = 0

    for user_data in data.values():
        for game, time_spent in user_data.items():
            if time_spent > 0:
                all_games[game]["players"] += 1
                all_games[game]["time"] += time_spent
                total_time_all_games += time_spent

    total_unique_games = len(all_games)

    most_popular_game_name: Optional[str] = None
    max_players = 0
    most_time_game_name: Optional[str] = None
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
    summary += f"⏱️ Общее время в играх: **{format_time_short(total_time_all_games)}**\n\n" # Краткий формат времени

    if most_popular_game_name:
        players_str = f"{max_players} {'игрока' if 2 <= max_players <= 4 else 'игроков'}" if max_players > 1 else "1 игрок"
        summary += f"🏆 Самая популярная игра: **{most_popular_game_name}** ({players_str})\n"
    if most_time_game_name and most_time_game_name != most_popular_game_name:
         # Показываем игру с наибольшим временем, только если она не совпадает с самой популярной
         summary += f"⭐ Игра с наибольшим временем: **{most_time_game_name}** ({format_time_short(max_time)})\n" # Краткий формат времени

    return summary

async def send_monthly_report(
    year: int,
    month: int,
    bot: discord.Client,
    data_manager: ActivityDataManager,
    config: Dict[str, Any],
    channel: Optional[discord.TextChannel] = None
) -> bool:
    """
    Получает данные за указанный месяц/год и отправляет ежемесячный отчет.

    Args:
        year: Год.
        month: Месяц.
        bot: Экземпляр бота Discord.
        data_manager: Экземпляр ActivityDataManager.
        config: Словарь конфигурации бота.
        channel: Канал для отправки отчета. Если None, будет использован канал из конфигурации.

    Returns:
        True, если отчет успешно отправлен (или данных не было), False при ошибке.
    """
    month_name = MONTH_NAMES_RU.get(month, f"Месяц {month}")
    logger.info(f"Запрос на отправку ежемесячного отчета за {month_name} {year}")
    
    # Если канал не указан, получаем его из конфигурации
    if channel is None:
        channel = await _get_report_channel(bot, config)
        if not channel:
            return False

    try:
        # Загружаем агрегированные данные за указанный месяц из БД
        data = await data_manager.get_aggregated_monthly_stats(year, month)

        if not data:
            await channel.send(f"Нет данных об активности за {month_name} {year} 😢")
            logger.info(f"Отправлено уведомление об отсутствии данных для ежемесячного отчета за {year}-{month:02d}.")
            return True # Считаем успехом

        # Формируем заголовок и основную часть отчета
        header = f"# 📊 Ежемесячный отчет за {month_name} {year}\n\n"
        content = "## 👤 Активность всех пользователей\n"
        content += "*(Показаны только игры с временем более 30 минут)*\n\n"
        guild = channel.guild # Получаем гильдию из канала для поиска участников

        # Получаем имена пользователей для сортировки по алфавиту
        users_with_names = []
        for user_id, activities in data.items():
            member = guild.get_member(user_id)
            username = member.name if member else f"Пользователь {user_id}"
            # Фильтруем игры с временем менее 30 минут (1800 секунд)
            filtered_activities = {game: time for game, time in activities.items() if time >= 1800}
            total_time = sum(activities.values())  # Общее время считаем по всем играм
            users_with_names.append((user_id, filtered_activities, username, total_time))

        # Сортируем пользователей по имени (алфавитный порядок)
        sorted_users = sorted(users_with_names, key=lambda x: x[2].lower())
        
        # Находим топ-3 игроков по игровому времени
        top_players = sorted(users_with_names, key=lambda x: x[3], reverse=True)[:3]
        
        # Максимальная длина сообщения Discord
        max_message_length = 1900  # Оставляем запас для форматирования
        
        # Формируем содержимое отчета
        current_message = content
        
        for user_id, activities, username, total_time_user in sorted_users:
            # Формируем строку для пользователя
            user_line = f"**{username}** (**{format_time_short(total_time_user)}**): "
            
            # Сортируем игры пользователя по времени
            sorted_activities = sorted(activities.items(), key=lambda item: item[1], reverse=True)
            
            # Используем краткий формат времени для отдельных игр
            games_list = [
                f"{game_name} ({format_time_short(time_spent)})"
                for game_name, time_spent in sorted_activities
            ]
            
            user_content = user_line + ", ".join(games_list) + "\n\n"
            
            # Проверяем, поместится ли пользователь в текущее сообщение
            if len(current_message) + len(user_content) > max_message_length:
                # Если не поместится, добавляем текущее сообщение в content и начинаем новое
                content = current_message
                current_message = user_content
            else:
                # Если поместится, добавляем к текущему сообщению
                current_message += user_content
        
        # Добавляем последнее сообщение
        content = current_message

        # Формируем информацию о топ-3 игроках
        top_players_text = "## 🏆 Топ-3 игрока по игровому времени\n"
        for i, (_, _, username, total_time) in enumerate(top_players, 1):
            top_players_text += f"{i}. **{username}** ({format_time_short(total_time)})\n"
        top_players_text += "\n"
        
        # Добавляем общую статистику
        summary_text = _get_monthly_summary_text(data, month, year)
        
        # Отправка сообщения (с разбивкой, если длинное)
        full_report = header + content + top_players_text + summary_text
        
        if len(full_report) <= 2000:
            await channel.send(full_report)
        else:
            # Отправляем заголовок
            await channel.send(header)
            
            # Отправляем основное содержимое
            if len(content) <= 2000:
                await channel.send(content)
            else:
                # Разбиваем на части, если содержимое слишком длинное
                # Используем более умный алгоритм разбивки, чтобы не разрывать информацию о пользователях
                current_chunk = ""
                lines = content.split("\n\n")
                
                for line in lines:
                    if len(current_chunk) + len(line) + 2 > 1990:  # +2 для "\n\n"
                        await channel.send(current_chunk)
                        current_chunk = line + "\n\n"
                        await asyncio.sleep(1)  # Небольшая задержка между частями
                    else:
                        current_chunk += line + "\n\n"
                
                if current_chunk:
                    await channel.send(current_chunk)
            
            # Отправляем топ-3 игроков и общую статистику
            final_part = top_players_text + summary_text
            if len(final_part) <= 2000:
                await channel.send(final_part)
            else:
                await channel.send(top_players_text)
                await channel.send(summary_text)

        logger.info(f"Отправлен ежемесячный отчет за {month_name} {year}")
        return True

    except Exception as e:
        logger.error(f"Ошибка при получении данных или отправке ежемесячного отчета за {year}-{month:02d}: {e}", exc_info=True)
        try:
            await channel.send(f"Не удалось сформировать ежемесячный отчет за {month_name} {year}. Ошибка: {e}")
        except Exception as send_e:
            logger.error(f"Не удалось отправить сообщение об ошибке генерации ежемесячного отчета: {send_e}")
        return False


# --- Функции для автоматического запуска из Cog ---

async def run_automatic_daily_report(cog_instance: Any):
    """
    Выполняет полную логику автоматического ежедневного отчета:
    1. Обновляет текущие сессии.
    2. Отправляет отчет за вчерашний день.
    3. Переносит данные daily -> monthly.

    Args:
        cog_instance: Экземпляр кога ActivityTracker (для доступа к bot, data_manager, config, update_current_activities).
    """
    bot = cog_instance.bot
    data_manager = cog_instance.data_manager
    config = getattr(bot, 'config', {}) # Получаем конфиг из бота

    try:
        # Получаем текущую дату в московском часовом поясе
        moscow_tz = pytz.timezone('Europe/Moscow')
        moscow_now = datetime.now(moscow_tz)
        today = moscow_now.date()
        yesterday = today - timedelta(days=1)
        logger.info(f"Запуск автоматической обработки ежедневного отчета. Текущая дата (МСК): {today.isoformat()}, вчерашняя дата: {yesterday.isoformat()}")

        # 1. Обновляем текущие сессии перед обработкой
        logger.debug("run_automatic_daily_report: Обновление текущих активностей...")
        await cog_instance.update_current_activities()
        logger.debug("run_automatic_daily_report: Обновление текущих активностей завершено.")

        # 2. Отправляем отчет
        await send_daily_report(yesterday, bot, data_manager, config)

        # 3. Переносим данные daily -> monthly и очищаем daily
        logger.info(f"run_automatic_daily_report: Запуск переноса данных за {yesterday.isoformat()}...")
        transfer_success = await data_manager.transfer_daily_to_monthly(yesterday)
        if not transfer_success:
            # Ошибка уже должна быть залогирована в data_manager
            logger.error(f"run_automatic_daily_report: Не удалось перенести дневные данные за {yesterday.isoformat()} в месячную статистику!")
        else:
            logger.info(f"run_automatic_daily_report: Дневные данные за {yesterday.isoformat()} успешно перенесены и удалены.")

    except Exception as e:
        # Логируем общую ошибку выполнения задачи
        logger.error(f"Критическая ошибка при выполнении автоматического ежедневного отчета: {e}", exc_info=True)


async def run_automatic_monthly_report(cog_instance: Any):
    """
    Выполняет логику автоматического ежемесячного отчета:
    1. Проверяет, является ли сегодня 1-е число.
    2. Определяет предыдущий месяц/год.
    3. Отправляет отчет за предыдущий месяц.

    Args:
        cog_instance: Экземпляр кога ActivityTracker (для доступа к bot, data_manager, config).
    """
    bot = cog_instance.bot
    data_manager = cog_instance.data_manager
    config = getattr(bot, 'config', {})

    try:
        # Получаем текущую дату в московском часовом поясе
        moscow_tz = pytz.timezone('Europe/Moscow')
        moscow_now = datetime.now(moscow_tz)
        today = moscow_now.date()
        logger.info(f"run_automatic_monthly_report: Проверка даты. Текущая дата (МСК): {today.isoformat()}, день месяца: {today.day}")
        if today.day != 1:
            logger.debug("run_automatic_monthly_report: Сегодня не 1-е число, отчет пропускается.")
            return # Запускаем только первого числа

        logger.info("run_automatic_monthly_report: Запуск формирования ежемесячного отчета за предыдущий месяц.")
        # Определяем предыдущий месяц и год
        first_day_of_current_month = today.replace(day=1)
        last_day_of_prev_month = first_day_of_current_month - timedelta(days=1)
        prev_month = last_day_of_prev_month.month
        prev_year = last_day_of_prev_month.year

        # Отправляем отчет
        await send_monthly_report(prev_year, prev_month, bot, data_manager, config)

    except Exception as e:
        logger.error(f"Критическая ошибка при выполнении автоматического ежемесячного отчета: {e}", exc_info=True)

# Функция для периодического сохранения остается простой и вызывается напрямую из кога
# async def run_periodic_save(cog_instance: Any):
#     try:
#         logger.debug("run_periodic_save: Обновление текущих активностей...")
#         await cog_instance.update_current_activities()
#     except Exception as e:
#         logger.error(f"Ошибка при периодическом обновлении активности (run_periodic_save): {e}", exc_info=True)
