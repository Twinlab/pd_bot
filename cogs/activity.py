import discord
from discord.ext import commands, tasks
import asyncio
import logging
# import json # Больше не нужен напрямую
# import os # Больше не нужен напрямую
from datetime import datetime, timedelta, time, date # Добавляем date
import pytz
from collections import defaultdict
from typing import Dict, Set, List, Tuple, DefaultDict, Optional
from discord import ui, ButtonStyle, Interaction

# Импортируем новый менеджер данных
from utils.activity_data_manager import ActivityDataManager

logger = logging.getLogger("bot")

# --- Представления (Views) остаются без изменений, т.к. они получают данные ---

class ActivityView(ui.View):
    """
    Интерактивное представление (View) для отображения статистики игровой активности.
    Позволяет переключаться между режимами "по пользователям" и "по играм",
    а также листать страницы с помощью кнопок.
    """

    def __init__(self, cog, data, ctx=None, report_type="daily"):
        super().__init__(timeout=86400)  # 24 часа таймаут
        self.cog = cog
        self.data = data  # Все данные о активности (дневные или месячные)
        self.ctx = ctx
        self.report_type = report_type  # "daily" или "command"
        self.current_page = 0
        self.view_mode = "users"  # "users" или "games"
        self.max_items_per_page = 20

        # Подготавливаем данные для отображения
        self.prepare_data()

        # Сразу устанавливаем правильную надпись на кнопке переключения режима
        for item in self.children:
            if isinstance(item, ui.Button) and item.label == "Режим":
                item.label = "По играм"
                break

    def prepare_data(self):
        """
        Подготавливает и сортирует данные для отображения в режимах "по пользователям" и "по играм".
        Фильтрует игры с нулевым временем. Рассчитывает максимальное количество страниц.
        """
        # Отображение по пользователям
        # Данные уже должны быть отфильтрованы менеджером данных, но на всякий случай
        self.users_data = {}
        for user_id, activities in self.data.items():
            filtered_activities = {game: time for game, time in activities.items() if time > 0}
            if filtered_activities:
                self.users_data[user_id] = filtered_activities

        # Создаем список пользователей, отсортированный по алфавиту
        guild = self.ctx.guild if self.ctx else next(iter(self.cog.bot.guilds))

        def get_username(user_id):
            member = guild.get_member(user_id)
            return member.name.lower() if member else f"user_{user_id}"

        # Сортируем пользователей по алфавиту
        self.user_ids = sorted(self.users_data.keys(), key=get_username)

        # Отображение по играм
        self.games_data = defaultdict(dict)
        for user_id, activities in self.users_data.items():
            for game, time in activities.items():
                if time > 0:
                    self.games_data[game][user_id] = time

        # Создаем список игр, отсортированный по популярности
        self.games_list = sorted(
            self.games_data.keys(),
            key=lambda g: (len(self.games_data[g]), sum(self.games_data[g].values())),
            reverse=True
        )

        # Считаем общее количество страниц
        if self.view_mode == "users":
            self.max_pages = max(1, (len(self.user_ids) + self.max_items_per_page - 1) // self.max_items_per_page)
        else:
            self.max_pages = max(1, (len(self.games_list) + self.max_items_per_page - 1) // self.max_items_per_page)

    def get_current_content(self):
        """Возвращает текущее содержимое для отображения"""
        header = f"# 📊 {'Ежедневный отчет' if self.report_type == 'daily' else 'Статистика'} игровой активности\n\n"
        if self.view_mode == "users":
            content = self._get_users_content()
        else:
            content = self._get_games_content()
        footer = f"\n*Страница {self.current_page + 1}/{self.max_pages}*"
        return header + content + footer

    def _get_users_content(self):
        """Получает содержимое для отображения пользователей"""
        content = "## 👤 По пользователям\n"
        start_idx = self.current_page * self.max_items_per_page
        end_idx = min(start_idx + self.max_items_per_page, len(self.user_ids))
        current_user_ids = self.user_ids[start_idx:end_idx]

        if not current_user_ids:
            return content + "*Нет данных для отображения*"

        guild = self.ctx.guild if self.ctx else next(iter(self.cog.bot.guilds))
        for user_id in current_user_ids:
            member = guild.get_member(user_id)
            username = member.name if member else f"Пользователь {user_id}"
            content += f"**{username}**: "
            activities = sorted(
                self.users_data[user_id].items(),
                key=lambda x: x[1],
                reverse=True
            )
            games_list = [
                f"{game_name} ({self.cog.format_time_short(time_spent)})"
                for game_name, time_spent in activities
                if time_spent > 0
            ]
            content += ", ".join(games_list) + "\n"

        content += "\n" + self._get_summary()
        return content

    def _get_games_content(self):
        """Получает содержимое для отображения игр"""
        content = "## 🎮 По играм\n"
        start_idx = self.current_page * self.max_items_per_page
        end_idx = min(start_idx + self.max_items_per_page, len(self.games_list))
        current_games = self.games_list[start_idx:end_idx]

        if not current_games:
            return content + "*Нет данных для отображения*"

        for game_name in current_games:
            players = self.games_data[game_name]
            total_time = sum(players.values())
            players_count = len(players)

            if total_time <= 0:
                continue

            players_info = f"{players_count} players" if players_count > 1 else ""
            if players_info:
                content += f"**{game_name}**: {players_info} ⏱️ {self.cog.format_time_short(total_time)}\n"
            else:
                content += f"**{game_name}**: ⏱️ {self.cog.format_time_short(total_time)}\n"

        content += "\n" + self._get_summary()
        return content

    def _get_summary(self):
        """Возвращает общую статистику"""
        total_users = len(self.users_data)
        total_games = len(self.games_data)
        most_popular_game = None
        max_players = 0
        for game, players in self.games_data.items():
            if len(players) > max_players:
                max_players = len(players)
                most_popular_game = game

        total_time = sum(sum(user_data.values()) for user_data in self.users_data.values())

        summary = f"## 📊 Общая статистика\n"
        summary += f"Всего игроков: {total_users} | "
        summary += f"Уникальных игр: {total_games} | "
        summary += f"Общее время: {self.cog.format_time_short(total_time)}"
        if most_popular_game:
            summary += f"\nСамая популярная игра: **{most_popular_game}** ({max_players} players)" if max_players > 1 else f"\nСамая популярная игра: **{most_popular_game}**"
        return summary

    @ui.button(label="⬅️ Назад", style=ButtonStyle.gray)
    async def previous_button(self, interaction: Interaction, button: ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(content=self.get_current_content(), view=self)
        else:
            await interaction.response.defer()

    @ui.button(label="По играм", style=ButtonStyle.blurple)
    async def toggle_mode(self, interaction: Interaction, button: ui.Button):
        self.view_mode = "games" if self.view_mode == "users" else "users"
        self.current_page = 0
        self.prepare_data()
        button.label = "По играм" if self.view_mode == "users" else "По пользователям"
        await interaction.response.edit_message(content=self.get_current_content(), view=self)

    @ui.button(label="Вперед ➡️", style=ButtonStyle.gray)
    async def next_button(self, interaction: Interaction, button: ui.Button):
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(content=self.get_current_content(), view=self)
        else:
            await interaction.response.defer()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except: pass

class StatsView(ui.View):
    """
    Интерактивное представление (View) для пагинации статистики игр пользователя
    (используется командами /mystats и /mystatsall).
    Отображает статистику в виде эмбеда и позволяет листать страницы.
    """
    def __init__(self, cog, title, games_data, user=None, items_per_page=5, all_time=False):
        super().__init__(timeout=86400)
        self.cog = cog
        self.title = title
        self.games_data = games_data
        self.user = user
        self.items_per_page = items_per_page
        self.current_page = 0
        self.all_time = all_time
        self.max_pages = max(1, (len(self.games_data) + self.items_per_page - 1) // self.items_per_page)

    def get_current_embed(self):
        """Возвращает текущий эмбед для отображения"""
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        if self.user:
            embed.set_thumbnail(url=self.user.display_avatar.url)

        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.games_data))
        current_games = self.games_data[start_idx:end_idx]

        description = ""
        for i, (game_name, time_spent) in enumerate(current_games, start_idx + 1):
            formatted_time = self.cog.format_time_short(time_spent)
            description += f"{i}. {game_name} - {formatted_time}\n"

        if description:
            embed.description = description

        total_time = sum(game[1] for game in self.games_data)
        embed.add_field(
            name="📊 Общее игровое время",
            value=f"{self.cog.format_time_short(total_time)}",
            inline=False
        )

        if self.max_pages > 1:
            footer_text = f"Всего игр: {len(self.games_data)} • Страница {self.current_page + 1}/{self.max_pages}"
        else:
            footer_text = f"Всего игр: {len(self.games_data)}"
        embed.set_footer(text=footer_text)
        return embed

    @ui.button(label="⬅️ Назад", style=ButtonStyle.gray)
    async def previous_button(self, interaction: Interaction, button: ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        else:
            await interaction.response.defer()

    @ui.button(label="Вперед ➡️", style=ButtonStyle.gray)
    async def next_button(self, interaction: Interaction, button: ui.Button):
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        else:
            await interaction.response.defer()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except: pass

# --- Основной Ког ---

class ActivityTracker(commands.Cog):
    """Отслеживает игровую активность пользователей на сервере"""

    def __init__(self, bot):
        self.bot = bot
        self.data_manager = ActivityDataManager() # Используем новый менеджер с SQLite
        logger.info(f"Инициализация ActivityTracker")
        self.current_activities: Dict[int, Tuple[str, datetime]] = {} # Активные сессии в памяти
        self.scan_scheduled = False
        # Запуск задач
        self.daily_report.start()
        self.monthly_report.start()
        self.periodic_save.start()

    @commands.Cog.listener()
    async def on_ready(self):
        """Запускает сканирование активности после загрузки бота"""
        if not self.scan_scheduled:
            self.scan_scheduled = True
            await self.scan_all_users_activity()

    async def scan_all_users_activity(self):
        """Сканирует активность всех пользователей при запуске бота"""
        await self.bot.wait_until_ready()
        logger.info("Начинаем сканирование активности всех пользователей")
        try:
            now = datetime.now(pytz.UTC)
            for guild in self.bot.guilds:
                for member in guild.members:
                    if member.bot or self.is_application(member):
                        continue
                    playing_games = []
                    for activity in member.activities:
                        if activity.type == discord.ActivityType.playing:
                            playing_games.append(activity.name)
                            logger.info(f"Обнаружена активная игра у пользователя {member.name}: {activity.name}")
                    if playing_games:
                        self.current_activities[member.id] = (playing_games[0], now)
            logger.info(f"Сканирование завершено. Обнаружено {len(self.current_activities)} активных игроков.")
            # Обновляем статистику в БД для активных игроков после сканирования
            if self.current_activities:
                await self.update_current_activities()
        except Exception as e:
            logger.error(f"Ошибка при сканировании активности пользователей: {e}", exc_info=True)

    def is_application(self, member):
        """Проверяет, является ли участник приложением (например, minecraft bot)"""
        app_names = ["minecraft bot"]
        if member.name in app_names: return True
        app_role_names = ["BOT", "APP", "Application"]
        if any(role.name in app_role_names for role in member.roles): return True
        return False

    def cog_unload(self):
        """Останавливает задачи при выгрузке кога"""
        self.daily_report.cancel()
        self.monthly_report.cancel()
        self.periodic_save.cancel()
        # Пытаемся сохранить последние данные об активности
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                 loop.create_task(self.update_current_activities())
                 logger.info("Запланировано финальное обновление активности перед выгрузкой...")
            else:
                 logger.warning("Цикл событий остановлен, финальное обновление активности не может быть запланировано.")
        except Exception as e:
            logger.error(f"Ошибка при планировании финального обновления активности во время выгрузки: {e}")
        logger.info("ActivityTracker выгружен.")

    # --- Форматирование времени (остается в коге) ---
    def format_time(self, seconds: int) -> str:
        """Форматирует время в секундах в удобочитаемую строку"""
        if seconds <= 0: return "0 минут"
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            if minutes > 0:
                return f"{hours} час{'ов' if hours >= 5 or hours == 0 else 'а' if hours >= 2 else ''} и {minutes} минут{'а' if minutes == 1 else '' if minutes >= 5 or minutes == 0 else 'ы'}"
            else:
                return f"{hours} час{'ов' if hours >= 5 or hours == 0 else 'а' if hours >= 2 else ''}"
        else:
            return f"{minutes} минут{'а' if minutes == 1 else '' if minutes >= 5 or minutes == 0 else 'ы'}"

    def format_time_short(self, seconds: int) -> str:
        """Форматирует время в секундах в краткую строку (1h 5m)"""
        if seconds <= 0: return "0m"
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            if minutes > 0: return f"{hours}h {minutes}m"
            else: return f"{hours}h"
        else: return f"{minutes}m"

    # --- Логика обновления активности ---
    async def update_current_activities(self):
        """
        Обновляет статистику для текущих активностей, записывая данные в БД.
        Вызывается периодически и при завершении сессии.
        """
        now = datetime.now(pytz.UTC)
        tasks = []
        users_to_update_start_time = {}

        for user_id, (game_name, start_time) in list(self.current_activities.items()):
            elapsed_seconds = int((now - start_time).total_seconds())

            if elapsed_seconds > 10:  # Минимальный порог в секундах
                tasks.append(self.data_manager.update_activity(user_id, game_name, elapsed_seconds))
                users_to_update_start_time[user_id] = (game_name, now)
            elif elapsed_seconds < -60: # Обработка возможной смены системного времени
                logger.warning(f"Обнаружено отрицательное время ({elapsed_seconds}s) для {user_id} в {game_name}. Сбрасываем время начала.")
                self.current_activities[user_id] = (game_name, now) # Обновляем только в памяти

        if not tasks: return # Если нечего обновлять в БД

        try:
            await asyncio.gather(*tasks) # Выполняем запись в БД
            # Обновляем время старта в памяти ПОСЛЕ успешной записи
            for user_id, new_start_data in users_to_update_start_time.items():
                if user_id in self.current_activities and self.current_activities[user_id][0] == new_start_data[0]:
                    self.current_activities[user_id] = new_start_data
            logger.info(f"Обновлена активность в БД для {len(users_to_update_start_time)} пользователей.")
        except Exception as e:
            logger.error(f"Ошибка при пакетном обновлении активности в БД: {e}", exc_info=True)
            # НЕ обновляем время старта в памяти при ошибке

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """Отслеживает изменения статуса пользователей для учета игровой активности"""
        if after.bot or self.is_application(after): return
        try:
            now = datetime.now(pytz.UTC)
            user_id = after.id
            before_games = {act.name: act for act in before.activities if act.type == discord.ActivityType.playing}
            after_games = {act.name: act for act in after.activities if act.type == discord.ActivityType.playing}

            if before_games.keys() == after_games.keys(): return # Нет изменений

            logger.debug(f"Изменение игровых активностей пользователя {after.name}: {list(before_games.keys())} -> {list(after_games.keys())}")

            # Новые игры
            for game_name in after_games.keys() - before_games.keys():
                self.current_activities[user_id] = (game_name, now)
                logger.debug(f"Пользователь {after.name} начал играть в {game_name}")

            # Завершенные игры
            for game_name in before_games.keys() - after_games.keys():
                if user_id in self.current_activities and self.current_activities[user_id][0] == game_name:
                    start_time = self.current_activities[user_id][1]
                    elapsed_seconds = int((now - start_time).total_seconds())
                    if elapsed_seconds > 0:
                        # Обновляем статистику в БД асинхронно
                        asyncio.create_task(self.data_manager.update_activity(user_id, game_name, elapsed_seconds))

                    if not after_games: # Если больше не играет ни во что
                        del self.current_activities[user_id]
                        logger.debug(f"Пользователь {after.name} закончил играть в {game_name}, общее время: {self.format_time(elapsed_seconds)}")
                    else: # Если переключился на другую игру
                        next_game = next(iter(after_games.keys()))
                        self.current_activities[user_id] = (next_game, now)
                        logger.debug(f"Пользователь {after.name} закончил играть в {game_name} и продолжает играть в {next_game}")
        except Exception as e:
            logger.error(f"Ошибка при обработке изменения присутствия: {e}", exc_info=True)

    # --- Фоновые задачи ---
    @tasks.loop(minutes=5)
    async def periodic_save(self):
        """Периодически обновляет время текущих активных сессий в БД"""
        try:
            await self.update_current_activities()
        except Exception as e:
            logger.error(f"Ошибка при периодическом обновлении активности: {e}", exc_info=True)

    @periodic_save.before_loop
    async def before_periodic_save(self):
        await self.bot.wait_until_ready()
        logger.info("Запущена задача периодического обновления активности")

    # month_checker удален

    @tasks.loop(time=time(hour=9, minute=0))  # 12:00 по МСК (UTC+3)
    async def monthly_report(self):
        """Отправляет ежемесячный отчет об активности всех пользователей за предыдущий месяц"""
        try:
            today = date.today()
            if today.day != 1: return # Только первого числа
            logger.info("Начинаем формирование ежемесячного отчета за предыдущий месяц")
            first_day_of_current_month = today.replace(day=1)
            last_day_of_prev_month = first_day_of_current_month - timedelta(days=1)
            prev_month = last_day_of_prev_month.month
            prev_year = last_day_of_prev_month.year

            # Загружаем агрегированные данные за предыдущий месяц из БД
            data = await self.data_manager.get_aggregated_monthly_stats(prev_year, prev_month)

            report_channel_id = self.bot.config.get("REPORT_CHANNEL_ID", 573665353327181824)
            channel = self.bot.get_channel(report_channel_id)
            if not channel:
                logger.error(f"Канал для отчетов (ID: {report_channel_id}) не найден")
                return

            month_names = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь", 7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"}
            month_name = month_names.get(prev_month, f"Месяц {prev_month}")

            if not data:
                await channel.send(f"Нет данных об активности за {month_name} {prev_year} 😢")
                return

            header = f"# 📊 Ежемесячный отчет за {month_name} {prev_year}\n\n"
            content = "## 👤 Активность всех пользователей\n"
            guild = channel.guild

            def get_total_time(user_data): return sum(user_data.values())
            sorted_users = sorted(data.items(), key=lambda x: get_total_time(x[1]), reverse=True)

            for user_id, activities in sorted_users:
                member = guild.get_member(user_id)
                username = member.name if member else f"Пользователь {user_id}"
                total_time = get_total_time(activities)
                content += f"**{username}** (всего: {self.format_time(total_time)}): "
                sorted_activities = sorted(activities.items(), key=lambda x: x[1], reverse=True)
                games_list = [f"{game_name} ({self.format_time_short(time_spent)})" for game_name, time_spent in sorted_activities if time_spent > 0]
                content += ", ".join(games_list) + "\n\n"

            content += self._get_monthly_summary(data, prev_month, prev_year)

            # Отправка сообщения (с разбивкой, если нужно)
            if len(header + content) <= 2000:
                await channel.send(header + content)
            else:
                await channel.send(header)
                chunks = [content[i:i+1990] for i in range(0, len(content), 1990)]
                for chunk in chunks:
                    await channel.send(chunk)
                    await asyncio.sleep(1)
            logger.info(f"Отправлен ежемесячный отчет за {month_name} {prev_year}")
        except Exception as e:
            logger.error(f"Ошибка при отправке ежемесячного отчета: {e}", exc_info=True)

    @monthly_report.before_loop
    async def before_monthly_report(self):
        await self.bot.wait_until_ready()
        logger.info("Запущена задача ежемесячного отчета об активности")

    def _get_monthly_summary(self, data, month, year):
        """Возвращает общую статистику для месячного отчета"""
        total_users = len(data)
        all_games = set(game for user_data in data.values() for game in user_data)
        total_games = len(all_games)
        game_players = defaultdict(int)
        game_time = defaultdict(int)
        for user_data in data.values():
            for game, time_spent in user_data.items():
                game_players[game] += 1
                game_time[game] += time_spent
        most_played_game = max(game_players.items(), key=lambda x: x[1], default=("Нет данных", 0))
        most_time_game = max(game_time.items(), key=lambda x: x[1], default=("Нет данных", 0))
        total_time = sum(game_time.values())

        summary = f"## 📊 Общая статистика за {month}/{year}\n"
        summary += f"👥 Всего активных игроков: **{total_users}**\n"
        summary += f"🎮 Уникальных игр: **{total_games}**\n"
        summary += f"⏱️ Общее время в играх: **{self.format_time(total_time)}**\n\n"
        if most_played_game[0] != "Нет данных":
            summary += f"🏆 Самая популярная игра: **{most_played_game[0]}** ({most_played_game[1]} игроков)\n"
        if most_time_game[0] != "Нет данных" and most_time_game[0] != most_played_game[0]:
            summary += f"⭐ Игра с наибольшим временем: **{most_time_game[0]}** ({self.format_time(most_time_game[1])})\n"
        return summary

    @tasks.loop(time=time(hour=21, minute=0))  # 00:00 по МСК (UTC+3)
    async def daily_report(self):
        """
        Отправляет ежедневный отчет об активности за прошедший день,
        переносит дневные данные в месячную статистику и очищает дневные.
        """
        try:
            yesterday = date.today() - timedelta(days=1)
            logger.info(f"Начинаем формирование и обработку ежедневного отчета за {yesterday.isoformat()}")
            await self.update_current_activities() # Обновляем данные перед обработкой
            daily_data = await self.data_manager.get_daily_stats(yesterday) # Получаем данные за вчера

            # Отправка отчета
            report_channel_id = self.bot.config.get("REPORT_CHANNEL_ID", 573665353327181824)
            channel = self.bot.get_channel(report_channel_id)
            if not channel:
                logger.error(f"Канал для отчетов (ID: {report_channel_id}) не найден. Отчет не будет отправлен.")
            elif not daily_data:
                try:
                    await channel.send(f"За {yesterday.strftime('%d.%m.%Y')} никто не играл в игры 😢")
                    logger.info("Отправлено уведомление об отсутствии данных для ежедневного отчета.")
                except Exception as send_e: logger.error(f"Ошибка при отправке уведомления об отсутствии данных: {send_e}", exc_info=True)
            else:
                try:
                    view = ActivityView(self, daily_data, report_type="daily")
                    message = await channel.send(content=view.get_current_content(), view=view)
                    view.message = message
                    logger.info(f"Отправлен ежедневный отчет за {yesterday.isoformat()}")
                except Exception as send_e: logger.error(f"Ошибка при отправке ежедневного отчета: {send_e}", exc_info=True)

            # Перенос данных daily -> monthly и очистка daily
            transfer_success = await self.data_manager.transfer_daily_to_monthly(yesterday)
            if not transfer_success: logger.error(f"Не удалось перенести дневные данные за {yesterday.isoformat()} в месячную статистику!")
            else: logger.info(f"Дневные данные за {yesterday.isoformat()} успешно перенесены и удалены.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении ежедневного отчета: {e}", exc_info=True)

    @daily_report.before_loop
    async def before_daily_report(self):
        await self.bot.wait_until_ready()
        logger.info("Запущена задача ежедневного отчета об активности")

    # --- Команды ---
    @commands.hybrid_command(description='Показать текущую статистику игровой активности или тест отчета')
    @commands.has_permissions(administrator=True)
    async def activity(self, ctx, test_mode: bool = False):
        """Показывает текущую статистику игровой активности за СЕГОДНЯ"""
        try:
            await self.update_current_activities() # Обновляем перед показом
            today_data = await self.data_manager.get_daily_stats(date.today())

            if not today_data and test_mode:
                # Создаем тестовые данные
                today_data = { ctx.author.id: {"Test Game 1": 3660, "Test Game 2": 1800} }
                # Добавляем еще пару юзеров для теста
                members = [m for m in ctx.guild.members if not m.bot and m.id != ctx.author.id][:2]
                if len(members) > 0: today_data[members[0].id] = {"Another Game": 7200}
                if len(members) > 1: today_data[members[1].id] = {"Test Game 1": 1200, "Third Game": 5000}

            if not today_data:
                await ctx.send("Сегодня пока никто не играл в игры 😢")
                return

            view = ActivityView(self, today_data, ctx=ctx, report_type="daily" if test_mode else "command")
            prefix = "**[ТЕСТ]** Так будет выглядеть ежедневный отчет:\n\n" if test_mode else ""
            message = await ctx.send(content=f"{prefix}{view.get_current_content()}", view=view)
            view.message = message
        except Exception as e:
            logger.error(f"Ошибка при показе статистики активности: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")

    @commands.hybrid_command(description='Показать статистику игровой активности пользователя')
    async def mystats(self, ctx, user: Optional[discord.Member] = None, month: Optional[int] = None, year: Optional[int] = None):
        """Показывает статистику игровой активности пользователя за месяц с пагинацией"""
        try:
            target_user = user if user else ctx.author
            user_id = target_user.id
            today = date.today()
            target_year = year if year is not None else today.year
            target_month = month if month is not None else today.month
            is_current_month = (target_year == today.year and target_month == today.month)

            if is_current_month: await self.update_current_activities() # Обновляем, если смотрим текущий месяц

            # Получаем данные
            data = await self.data_manager.get_monthly_stats(user_id, target_year, target_month)
            if is_current_month: # Добавляем сегодняшние данные
                today_stats = await self.data_manager.get_daily_stats(today)
                if user_id in today_stats:
                    for game, seconds in today_stats[user_id].items():
                        data[game] = data.get(game, 0) + seconds

            data_type = f"за {target_month}/{target_year}" if month is not None else "за текущий месяц"

            if not data:
                embed = discord.Embed(title=f"📊 Статистика {target_user.name}", description=f"Нет данных об активности {data_type} 😢", color=discord.Color.blue(), timestamp=datetime.now())
                embed.set_thumbnail(url=target_user.display_avatar.url)
                await ctx.send(embed=embed)
                return

            sorted_games = sorted(data.items(), key=lambda x: x[1], reverse=True)
            title = f"📊 Статистика {target_user.name} {data_type}"
            view = StatsView(self, title, sorted_games, user=target_user, items_per_page=5)
            message = await ctx.send(embed=view.get_current_embed(), view=view)
            view.message = message

            # Показываем текущую сессию эфемерно
            if is_current_month and user_id in self.current_activities:
                game_name, start_time = self.current_activities[user_id]
                now = datetime.now(pytz.UTC)
                current_session = int((now - start_time).total_seconds())
                if current_session > 10:
                    current_info = f"🔴 **{target_user.name}** сейчас играет в **{game_name}** (текущая сессия: {self.format_time_short(current_session)})"
                    await ctx.send(current_info, ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка при отображении персональной статистики: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")

    @commands.hybrid_command(name="mystatsall", description="Показывает статистику пользователя за всё время")
    async def mystatsall(self, ctx, user: Optional[discord.Member] = None):
        """Показывает статистику игровой активности пользователя за всё время с пагинацией"""
        try:
            target_user = user if user else ctx.author
            user_id = target_user.id
            await self.update_current_activities() # Обновляем перед получением
            all_user_games = await self.data_manager.get_all_time_stats(user_id)

            if not all_user_games:
                embed = discord.Embed(title=f"📊 Статистика {target_user.name}", description=f"Нет данных об активности за всё время 😢", color=discord.Color.blue(), timestamp=datetime.now())
                embed.set_thumbnail(url=target_user.display_avatar.url)
                await ctx.send(embed=embed)
                return

            sorted_games = sorted(all_user_games.items(), key=lambda x: x[1], reverse=True)
            title = f"📊 Статистика {target_user.name} за всё время"
            view = StatsView(self, title, sorted_games, user=target_user, items_per_page=10, all_time=True)
            message = await ctx.send(embed=view.get_current_embed(), view=view)
            view.message = message
        except Exception as e:
            logger.error(f"Ошибка при выполнении команды mystatsall: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")

    # --- Обработчики ошибок ---
    @activity.error
    async def activity_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас недостаточно прав для использования этой команды. Требуются права администратора.", ephemeral=True)
        else:
            logger.error(f"Ошибка в команде activity: {error}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {error}", ephemeral=True)

    @mystats.error
    async def mystats_error(self, ctx, error):
        if isinstance(error, commands.UserNotFound):
            await ctx.send("Не удалось найти указанного пользователя. Проверьте правильность имени или ID.", ephemeral=True)
        else:
            logger.error(f"Ошибка в команде mystats: {error}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {error}", ephemeral=True)

    @mystatsall.error
    async def mystatsall_error(self, ctx, error):
        if isinstance(error, commands.UserNotFound):
            await ctx.send("Не удалось найти указанного пользователя. Проверьте правильность имени или ID.", ephemeral=True)
        else:
            logger.error(f"Ошибка в команде mystatsall: {error}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {error}", ephemeral=True)

async def setup(bot):
    """Загружает ког ActivityTracker"""
    await bot.add_cog(ActivityTracker(bot))
