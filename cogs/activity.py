import discord
from discord.ext import commands, tasks
import asyncio
import logging
import json
import os
from datetime import datetime, timedelta, time
import pytz
from collections import defaultdict
from typing import Dict, Set, List, Tuple, DefaultDict, Optional
from discord import ui, ButtonStyle, Interaction

logger = logging.getLogger("bot")

class ActivityView(ui.View):
    """Интерактивное представление статистики активности с кнопками"""
    
    def __init__(self, cog, data, ctx=None, report_type="daily"):
        super().__init__(timeout=86400)  # 24 часа таймаут (увеличен с 1800 до 86400)
        self.cog = cog
        self.data = data  # Все данные о активности
        self.ctx = ctx
        self.report_type = report_type  # "daily" или "command"
        self.current_page = 0
        self.view_mode = "users"  # "users" или "games"
        self.max_items_per_page = 20  # 20 элементов на страницу
        
        # Подготавливаем данные для отображения
        self.prepare_data()
        
        # Сразу устанавливаем правильную надпись на кнопке переключения режима
        for item in self.children:
            if isinstance(item, ui.Button) and item.label == "Режим":
                item.label = "По играм"
                break
    
    def prepare_data(self):
        """Подготавливает данные для отображения - фильтрует игры с нулевым временем"""
        # Отображение по пользователям
        self.users_data = {}
        for user_id, activities in self.data.items():
            # Отфильтровываем строго больше 0 (не менее или равно)
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
        for user_id, activities in self.users_data.items():  # Используем уже отфильтрованные данные
            for game, time in activities.items():
                # Двойная проверка, что время > 0
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
    
    def format_time_short(self, seconds: int) -> str:
        """Форматирует время в секундах в краткую строку (1h 5m)"""
        # Проверка на положительное значение
        if seconds <= 0:
            return "0m"
            
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if hours > 0:
            if minutes > 0:
                return f"{hours}h {minutes}m"  # Пробел между часами и минутами
            else:
                return f"{hours}h"
        else:
            return f"{minutes}m"
    
    def get_current_content(self):
        """Возвращает текущее содержимое для отображения"""
        # Заголовок
        header = f"# 📊 {'Ежедневный отчет' if self.report_type == 'daily' else 'Статистика'} игровой активности\n\n"
        
        # Содержимое зависит от режима просмотра и текущей страницы
        if self.view_mode == "users":
            content = self._get_users_content()
        else:
            content = self._get_games_content()
        
        # Добавляем информацию о страницах (упрощенная)
        footer = f"\n*Страница {self.current_page + 1}/{self.max_pages}*"
        
        return header + content + footer
    
    def _get_users_content(self):
        """Получает содержимое для отображения пользователей"""
        content = "## 👤 По пользователям\n"
        
        # Получаем нужные ID пользователей для текущей страницы
        start_idx = self.current_page * self.max_items_per_page
        end_idx = min(start_idx + self.max_items_per_page, len(self.user_ids))
        current_user_ids = self.user_ids[start_idx:end_idx]
        
        if not current_user_ids:
            return content + "*Нет данных для отображения*"
        
        # Формируем строки для каждого пользователя
        for user_id in current_user_ids:
            # Получаем имя пользователя - используем глобальное имя, а не серверное
            guild = self.ctx.guild if self.ctx else next(iter(self.cog.bot.guilds))
            member = guild.get_member(user_id)
            username = member.name if member else f"Пользователь {user_id}"
            
            content += f"**{username}**: "
            
            # Отсортированные активности
            activities = sorted(
                self.users_data[user_id].items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            # Добавляем только игры с ненулевым временем
            games_list = [
                f"{game_name} ({self.format_time_short(time_spent)})" 
                for game_name, time_spent in activities 
                if time_spent > 0  # Дополнительная проверка
            ]
            content += ", ".join(games_list) + "\n"
        
        # Добавляем общую статистику
        content += "\n" + self._get_summary()
        
        return content
    
    def _get_games_content(self):
        """Получает содержимое для отображения игр"""
        content = "## 🎮 По играм\n"
        
        # Получаем нужные игры для текущей страницы
        start_idx = self.current_page * self.max_items_per_page
        end_idx = min(start_idx + self.max_items_per_page, len(self.games_list))
        current_games = self.games_list[start_idx:end_idx]
        
        if not current_games:
            return content + "*Нет данных для отображения*"
        
        # Формируем строки для каждой игры в более компактном формате
        for game_name in current_games:
            players = self.games_data[game_name]
            total_time = sum(players.values())
            players_count = len(players)
            
            # Проверяем, что общее время > 0
            if total_time <= 0:
                continue
                
            # Не показываем количество игроков, если игрок всего один
            players_info = f"{players_count} players" if players_count > 1 else ""
            
            # Форматируем строку с информацией о игре
            if players_info:
                content += f"**{game_name}**: {players_info} ⏱️ {self.format_time_short(total_time)}\n"
            else:
                content += f"**{game_name}**: ⏱️ {self.format_time_short(total_time)}\n"
        
        # Добавляем общую статистику
        content += "\n" + self._get_summary()
        
        return content
    
    def _get_summary(self):
        """Возвращает общую статистику"""
        total_users = len(self.users_data)
        total_games = len(self.games_data)
        
        # Самая популярная игра
        most_popular_game = None
        max_players = 0
        
        for game, players in self.games_data.items():
            if len(players) > max_players:
                max_players = len(players)
                most_popular_game = game
        
        # Общее время всех игроков
        total_time = 0
        for user_data in self.users_data.values():
            total_time += sum(user_data.values())
        
        summary = f"## 📊 Общая статистика\n"
        summary += f"Всего игроков: {total_users} | "
        summary += f"Уникальных игр: {total_games} | "
        summary += f"Общее время: {self.format_time_short(total_time)}"
        
        if most_popular_game:
            summary += f"\nСамая популярная игра: **{most_popular_game}** ({max_players} players)" if max_players > 1 else f"\nСамая популярная игра: **{most_popular_game}**"
        
        return summary
    
    @ui.button(label="⬅️ Назад", style=ButtonStyle.gray)
    async def previous_button(self, interaction: Interaction, button: ui.Button):
        """Переход на предыдущую страницу"""
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(content=self.get_current_content(), view=self)
        else:
            await interaction.response.defer()
    
    @ui.button(label="По играм", style=ButtonStyle.blurple)
    async def toggle_mode(self, interaction: Interaction, button: ui.Button):
        """Переключение между режимами отображения"""
        self.view_mode = "games" if self.view_mode == "users" else "users"
        self.current_page = 0  # Сброс страницы при смене режима
        self.prepare_data()  # Перерасчет данных для нового режима
        
        button.label = "По играм" if self.view_mode == "users" else "По пользователям"
        
        await interaction.response.edit_message(content=self.get_current_content(), view=self)
    
    @ui.button(label="Вперед ➡️", style=ButtonStyle.gray)
    async def next_button(self, interaction: Interaction, button: ui.Button):
        """Переход на следующую страницу"""
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(content=self.get_current_content(), view=self)
        else:
            await interaction.response.defer()
    
    async def on_timeout(self):
        """Обработка таймаута интерактивного сообщения"""
        # Отключаем все кнопки
        for item in self.children:
            item.disabled = True
        
        # Обновляем сообщение, если оно еще доступно
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass


# НОВЫЙ КЛАСС: Представление для пагинации статистики
class StatsView(ui.View):
    """Интерактивное представление для пагинации статистики"""
    
    def __init__(self, cog, title, games_data, user=None, items_per_page=5, all_time=False):
        super().__init__(timeout=86400)  # 24 часа таймаут
        self.cog = cog
        self.title = title
        self.games_data = games_data  # Должен быть список кортежей (game_name, time_spent)
        self.user = user
        self.items_per_page = items_per_page
        self.current_page = 0
        self.all_time = all_time  # Флаг для отображения "за все время"
        
        # Рассчитываем количество страниц
        self.max_pages = max(1, (len(self.games_data) + self.items_per_page - 1) // self.items_per_page)
    
    def get_current_embed(self):
        """Возвращает текущий эмбед для отображения"""
        # Создаем эмбед
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        # Если это статистика пользователя, добавляем аватар
        if self.user:
            embed.set_thumbnail(url=self.user.display_avatar.url)
        
        # Получаем игры для текущей страницы
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.games_data))
        current_games = self.games_data[start_idx:end_idx]
        
        # Создаем одно поле с описанием вместо отдельных полей для каждой игры
        description = ""
        for i, (game_name, time_spent) in enumerate(current_games, start_idx + 1):
            # Используем краткий формат времени
            formatted_time = self.cog.format_time_short(time_spent)
            description += f"{i}. {game_name} - {formatted_time}\n"
        
        if description:
            embed.description = description
        
        # Добавляем общую статистику
        total_time = sum(game[1] for game in self.games_data)
        
        # Добавляем общее игровое время как поле
        embed.add_field(
            name="📊 Общее игровое время",
            value=f"{self.cog.format_time_short(total_time)}",
            inline=False
        )
        
        # Добавляем информацию о страницах
        if self.max_pages > 1:
            footer_text = f"Всего игр: {len(self.games_data)} • Страница {self.current_page + 1}/{self.max_pages}"
        else:
            footer_text = f"Всего игр: {len(self.games_data)}"
        
        embed.set_footer(text=footer_text)
        
        return embed
    
    @ui.button(label="⬅️ Назад", style=ButtonStyle.gray)
    async def previous_button(self, interaction: Interaction, button: ui.Button):
        """Переход на предыдущую страницу"""
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        else:
            await interaction.response.defer()
    
    @ui.button(label="Вперед ➡️", style=ButtonStyle.gray)
    async def next_button(self, interaction: Interaction, button: ui.Button):
        """Переход на следующую страницу"""
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        else:
            await interaction.response.defer()
    
    async def on_timeout(self):
        """Обработка таймаута интерактивного сообщения"""
        # Отключаем все кнопки
        for item in self.children:
            item.disabled = True
        
        # Обновляем сообщение, если оно еще доступно
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

class ActivityTracker(commands.Cog):
    """Отслеживает игровую активность пользователей на сервере"""
    
    def __init__(self, bot):
        self.bot = bot
        
        # Базовая директория для данных
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(base_dir, "data")
        self.archive_dir = os.path.join(self.data_dir, "activity_archives")
        
        # Создаем директории
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)
        
        # Разделяем дневные и месячные данные
        self.data_file = os.path.join(self.data_dir, "user_activities.json")  # Дневные данные
        self.monthly_file = os.path.join(self.data_dir, "monthly_activities.json")  # Месячные данные
        
        # Отслеживаем текущий месяц и год для архивирования
        self.current_month = datetime.now().month
        self.current_year = datetime.now().year
        
        logger.info(f"Инициализация ActivityTracker")
        
        self.user_activities = {}  # Дневная статистика
        self.monthly_activities = {}  # Месячная статистика
        self.current_activities = {}  # Текущие активные игры
        
        # Проверяем, нужна ли миграция данных
        self.check_data_migration()
        
        # Загружаем оба типа данных
        self.load_data()  # Дневные данные
        self.load_monthly_data()  # Месячные данные
        
        # Планируем сканирование активности на потом
        self.scan_scheduled = False
        
        # Запуск задач
        self.month_checker.start()
        self.daily_report.start()
        self.monthly_report.start()  # НОВАЯ ЗАДАЧА: ежемесячный отчет
        self.periodic_save.start()
    
    def filter_zero_values(self, data):
        """Удаляет записи с нулевым временем из данных активности"""
        filtered_data = {}
        for user_id, games in data.items():
            filtered_games = {game: time for game, time in games.items() if time > 0}
            if filtered_games:
                filtered_data[user_id] = filtered_games
        return filtered_data
    
    def check_data_migration(self):
        """Проверяет, нужна ли миграция данных из старого формата в новый"""
        try:
            # Если уже есть monthly_file, миграция не нужна
            if os.path.exists(self.monthly_file):
                return
                
            # Если есть старый файл с данными, нужно мигрировать их в месячный файл
            if os.path.exists(self.data_file) and os.path.getsize(self.data_file) > 0:
                logger.info("Обнаружен старый формат данных, выполняем миграцию...")
                
                # Загружаем старые данные
                with open(self.data_file, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                
                # Сохраняем их как месячные данные
                with open(self.monthly_file, "w", encoding="utf-8") as f:
                    json.dump(old_data, f, indent=2)
                
                # Очищаем дневные данные
                with open(self.data_file, "w", encoding="utf-8") as f:
                    json.dump({}, f)
                    
                logger.info("Миграция данных завершена: месячные данные сохранены, дневные данные сброшены")
                
        except Exception as e:
            logger.error(f"Ошибка при миграции данных: {e}", exc_info=True)

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
            
            # Получаем список всех серверов, к которым подключен бот
            for guild in self.bot.guilds:
                # Получаем список всех участников
                for member in guild.members:
                    # Пропускаем ботов и приложения
                    if member.bot or self.is_application(member):
                        continue
                    
                    # Проверяем все активности пользователя вместо только одной
                    playing_games = []
                    for activity in member.activities:
                        if activity.type == discord.ActivityType.playing:
                            playing_games.append(activity.name)
                            logger.info(f"Обнаружена активная игра у пользователя {member.name}: {activity.name}")
                    
                    # Если пользователь играет, записываем его текущую активность
                    if playing_games:
                        # Берем первую активную игру как текущую
                        self.current_activities[member.id] = (playing_games[0], now)
            
            logger.info(f"Сканирование завершено. Обнаружено {len(self.current_activities)} активных игроков.")
            
            # Сохраняем данные после сканирования
            if self.current_activities:
                self.save_data()
                self.save_monthly_data()
        
        except Exception as e:
            logger.error(f"Ошибка при сканировании активности пользователей: {e}", exc_info=True)
    
    def is_application(self, member):
        """Проверяет, является ли участник приложением (например, minecraft bot)"""
        # Проверяем по имени (можно настроить список имен)
        app_names = ["minecraft bot"]
        if member.name in app_names:
            return True
        
        # Проверяем по ID роли или другим признакам приложений
        app_role_names = ["BOT", "APP", "Application"]
        if any(role.name in app_role_names for role in member.roles):
            return True
        
        return False
    
    def cog_unload(self):
        """Останавливает задачи при выгрузке кога"""
        self.month_checker.cancel()
        self.daily_report.cancel()
        self.monthly_report.cancel()  # Останавливаем новую задачу
        self.periodic_save.cancel()
        
        # Сохраняем данные при выгрузке кога
        self.update_current_activities()
        self.save_data()
        self.save_monthly_data()
        logger.info("ActivityTracker выгружен, данные сохранены")
    
    def load_data(self):
        """Загружает дневные данные об активности"""
        try:
            if os.path.exists(self.data_file):
                # Проверяем, что файл не пустой
                if os.path.getsize(self.data_file) > 0:
                    logger.info(f"Загрузка дневных данных об активности")
                    with open(self.data_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # Преобразуем строковые ключи обратно в числа и фильтруем нулевые значения
                    self.user_activities = {}
                    for user_id, activities in data.items():
                        user_id = int(user_id)
                        filtered_activities = {game: time for game, time in activities.items() if time > 0}
                        if filtered_activities:
                            self.user_activities[user_id] = filtered_activities
                    
                    logger.info(f"Загружены дневные данные: {len(self.user_activities)} пользователей")
                else:
                    logger.info(f"Файл дневных данных пуст, создаем пустой словарь")
                    self.user_activities = {}
            else:
                logger.info(f"Файл дневных данных не найден, создан пустой словарь")
                self.user_activities = {}
                
                # Создаем пустой файл
                with open(self.data_file, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке дневных данных: {e}", exc_info=True)
            self.user_activities = {}
    
    def load_monthly_data(self):
        """Загружает месячные данные об активности"""
        try:
            if os.path.exists(self.monthly_file):
                # Проверяем, что файл не пустой
                if os.path.getsize(self.monthly_file) > 0:
                    logger.info(f"Загрузка месячных данных об активности")
                    with open(self.monthly_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # Преобразуем строковые ключи обратно в числа и фильтруем нулевые значения
                    self.monthly_activities = {}
                    for user_id, activities in data.items():
                        user_id = int(user_id)
                        filtered_activities = {game: time for game, time in activities.items() if time > 0}
                        if filtered_activities:
                            self.monthly_activities[user_id] = filtered_activities
                    
                    logger.info(f"Загружены месячные данные: {len(self.monthly_activities)} пользователей")
                else:
                    logger.info(f"Файл месячных данных пуст, создаем пустой словарь")
                    self.monthly_activities = {}
            else:
                logger.info(f"Файл месячных данных не найден, создан пустой словарь")
                self.monthly_activities = {}
                
                # Создаем пустой файл
                with open(self.monthly_file, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке месячных данных: {e}", exc_info=True)
            self.monthly_activities = {}
    
    def save_data(self):
        """Сохраняет дневные данные об активности в файл"""
        try:
            # Создаем директорию, если не существует
            directory = os.path.dirname(self.data_file)
            os.makedirs(directory, exist_ok=True)
            
            # Фильтруем данные перед сохранением
            filtered_data = self.filter_zero_values(self.user_activities)
            
            # Сначала записываем во временный файл
            temp_file = f"{self.data_file}.tmp"
            
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(filtered_data, f, indent=2)
            
            # Проверяем, что файл не пустой
            if os.path.getsize(temp_file) > 0:
                # Затем безопасно переименовываем
                os.replace(temp_file, self.data_file)
                logger.info(f"Дневные данные об активности успешно сохранены")
            else:
                logger.warning(f"Временный файл дневных данных пуст, не переименовываем")
                os.remove(temp_file)
                
        except Exception as e:
            logger.error(f"Ошибка при сохранении дневных данных: {e}", exc_info=True)
    
    def save_monthly_data(self):
        """Сохраняет месячные данные об активности в файл"""
        try:
            # Создаем директорию, если не существует
            directory = os.path.dirname(self.monthly_file)
            os.makedirs(directory, exist_ok=True)
            
            # Фильтруем данные перед сохранением
            filtered_data = self.filter_zero_values(self.monthly_activities)
            
            # Сначала записываем во временный файл
            temp_file = f"{self.monthly_file}.tmp"
            
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(filtered_data, f, indent=2)
            
            # Проверяем, что файл не пустой
            if os.path.getsize(temp_file) > 0:
                # Затем безопасно переименовываем
                os.replace(temp_file, self.monthly_file)
                logger.info(f"Месячные данные об активности успешно сохранены")
            else:
                logger.warning(f"Временный файл месячных данных пуст, не переименовываем")
                os.remove(temp_file)
                
        except Exception as e:
            logger.error(f"Ошибка при сохранении месячных данных: {e}", exc_info=True)
    
    def reset_daily_data(self):
        """Сбрасывает данные об активности на текущий день"""
        self.user_activities = {}
        self.save_data()
        logger.info("Дневные данные сброшены")
    
    def format_time(self, seconds: int) -> str:
        """Форматирует время в секундах в удобочитаемую строку"""
        # Проверка на положительное значение
        if seconds <= 0:
            return "0 минут"
            
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
        # Проверка на положительное значение
        if seconds <= 0:
            return "0m"
            
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if hours > 0:
            if minutes > 0:
                return f"{hours}h {minutes}m"  # Пробел между часами и минутами
            else:
                return f"{hours}h"
        else:
            return f"{minutes}m"
    
    def update_current_activities(self):
        """Обновляет статистику для текущих активностей"""
        now = datetime.now(pytz.UTC)
        for user_id, (game_name, start_time) in list(self.current_activities.items()):
            # Вычисляем проведенное время
            elapsed_seconds = int((now - start_time).total_seconds())
            
            # Обновляем статистику только если прошло некоторое время и оно больше 0
            if elapsed_seconds <= 10:  # Минимальный порог в секундах
                continue
                
            # Обновляем ДНЕВНУЮ статистику
            if user_id not in self.user_activities:
                self.user_activities[user_id] = {}
            
            if game_name not in self.user_activities[user_id]:
                self.user_activities[user_id][game_name] = elapsed_seconds
            else:
                self.user_activities[user_id][game_name] += elapsed_seconds
            
            # Обновляем МЕСЯЧНУЮ статистику одновременно
            if user_id not in self.monthly_activities:
                self.monthly_activities[user_id] = {}
            
            if game_name not in self.monthly_activities[user_id]:
                self.monthly_activities[user_id][game_name] = elapsed_seconds
            else:
                self.monthly_activities[user_id][game_name] += elapsed_seconds
            
            # Обновляем время начала
            self.current_activities[user_id] = (game_name, now)
    
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """
        Отслеживает изменения статуса пользователей для учета игровой активности
        """
        # Пропускаем ботов и приложения
        if after.bot or self.is_application(after):
            return
        
        try:
            # Получаем текущее время
            now = datetime.now(pytz.UTC)
            user_id = after.id
            
            # Получаем все игровые активности до и после обновления
            before_games = {}
            after_games = {}
            
            # Проверяем все активности до обновления
            for activity in before.activities:
                if activity.type == discord.ActivityType.playing:
                    before_games[activity.name] = activity
            
            # Проверяем все активности после обновления
            for activity in after.activities:
                if activity.type == discord.ActivityType.playing:
                    after_games[activity.name] = activity
            
            # Если не было изменений в игровых активностях, пропускаем
            if before_games.keys() == after_games.keys():
                return
                
            # Логируем изменения
            logger.debug(f"Изменение игровых активностей пользователя {after.name}: {list(before_games.keys())} -> {list(after_games.keys())}")
            
            # Обрабатываем новые игры (появились в after, но не было в before)
            for game_name in after_games.keys() - before_games.keys():
                # Пользователь начал играть в новую игру
                self.current_activities[user_id] = (game_name, now)
                logger.debug(f"Пользователь {after.name} начал играть в {game_name}")
            
            # Обрабатываем завершенные игры (были в before, но нет в after)
            for game_name in before_games.keys() - after_games.keys():
                # Пользователь перестал играть в какую-то игру
                if user_id in self.current_activities and self.current_activities[user_id][0] == game_name:
                    # Извлекаем время начала
                    start_time = self.current_activities[user_id][1]
                    
                    # Вычисляем проведенное время
                    elapsed_seconds = int((now - start_time).total_seconds())
                    
                    # Обновляем статистику только если было потрачено время > 0
                    if elapsed_seconds > 0:
                        # Обновляем ДНЕВНУЮ статистику
                        if user_id not in self.user_activities:
                            self.user_activities[user_id] = {}
                        
                        if game_name not in self.user_activities[user_id]:
                            self.user_activities[user_id][game_name] = elapsed_seconds
                        else:
                            self.user_activities[user_id][game_name] += elapsed_seconds
                        
                        # Обновляем МЕСЯЧНУЮ статистику одновременно
                        if user_id not in self.monthly_activities:
                            self.monthly_activities[user_id] = {}
                        
                        if game_name not in self.monthly_activities[user_id]:
                            self.monthly_activities[user_id][game_name] = elapsed_seconds
                        else:
                            self.monthly_activities[user_id][game_name] += elapsed_seconds
                    
                    # Удаляем текущую активность, если это была единственная игра
                    # Или обновляем на другую активную игру, если такие есть
                    if not after_games:
                        del self.current_activities[user_id]
                        logger.debug(f"Пользователь {after.name} закончил играть в {game_name}, общее время: {self.format_time(elapsed_seconds)}")
                    else:
                        # Выбираем другую активную игру как текущую
                        next_game = next(iter(after_games.keys()))
                        self.current_activities[user_id] = (next_game, now)
                        logger.debug(f"Пользователь {after.name} закончил играть в {game_name} и продолжает играть в {next_game}")
                    
                    # Сохраняем данные
                    self.save_data()
                    self.save_monthly_data()
        
        except Exception as e:
            logger.error(f"Ошибка при обработке изменения присутствия: {e}", exc_info=True)
    
    @tasks.loop(minutes=5)
    async def periodic_save(self):
        """Периодически сохраняет данные об активности"""
        try:
            # Обновляем текущие активности
            self.update_current_activities()
            
            # Сохраняем данные
            self.save_data()
            self.save_monthly_data()
        except Exception as e:
            logger.error(f"Ошибка при периодическом сохранении: {e}", exc_info=True)
    
    @periodic_save.before_loop
    async def before_periodic_save(self):
        """Ожидает готовности бота перед запуском задачи"""
        await self.bot.wait_until_ready()
        logger.info("Запущена задача периодического сохранения данных об активности")
    
    @tasks.loop(hours=12)  # Проверяем дважды в день
    async def month_checker(self):
        """Проверяет, не наступил ли новый месяц для архивирования данных"""
        now = datetime.now()
        if now.month != self.current_month or now.year != self.current_year:
            await self.archive_monthly_data()
            self.current_month = now.month
            self.current_year = now.year
            logger.info(f"Начат новый месяц: {self.current_month}/{self.current_year}")
    
    @month_checker.before_loop
    async def before_month_checker(self):
        """Ожидает готовности бота перед запуском задачи проверки месяца"""
        await self.bot.wait_until_ready()
        logger.info("Запущена задача ежемесячной проверки")
    
    async def archive_monthly_data(self):
        """Архивирует данные за текущий месяц и создает новый пустой файл"""
        try:
            # Обновляем текущие активности перед архивацией
            self.update_current_activities()
            self.save_data()
            self.save_monthly_data()
            
            # Определяем имя архивного файла (для завершившегося месяца)
            prev_month = self.current_month
            prev_year = self.current_year
            
            # Формируем имя файла в формате YYYY_MM.json
            archive_filename = f"activity_{prev_year}_{prev_month:02d}.json"
            archive_path = os.path.join(self.archive_dir, archive_filename)
            
            # Копируем месячные данные в архив, при этом фильтруя нулевые значения
            if os.path.exists(self.monthly_file) and os.path.getsize(self.monthly_file) > 0:
                # Фильтруем данные перед архивацией
                filtered_data = self.filter_zero_values(self.monthly_activities)
                
                # Сохраняем напрямую в архивный файл
                with open(archive_path, "w", encoding="utf-8") as f:
                    json.dump(filtered_data, f, indent=2)
                
                logger.info(f"Данные за {prev_month}/{prev_year} успешно архивированы: {archive_path}")
                
                # Сбрасываем месячные данные
                self.monthly_activities = {}
                self.save_monthly_data()
                logger.info("Месячные данные сброшены для нового месяца")
            else:
                logger.warning(f"Не удалось архивировать данные - файл месячных данных пуст или не существует")
                
        except Exception as e:
            logger.error(f"Ошибка при архивировании месячных данных: {e}", exc_info=True)
    
    def load_archived_data(self, year, month):
        """Загружает архивные данные за указанный месяц и год"""
        try:
            archive_filename = f"activity_{year}_{month:02d}.json"
            archive_path = os.path.join(self.archive_dir, archive_filename)
            
            if os.path.exists(archive_path) and os.path.getsize(archive_path) > 0:
                with open(archive_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Преобразуем строковые ключи обратно в числа и фильтруем нулевые значения
                archived_activities = {}
                for user_id, activities in data.items():
                    user_id = int(user_id)
                    filtered_activities = {game: time for game, time in activities.items() if time > 0}
                    if filtered_activities:
                        archived_activities[user_id] = filtered_activities
                
                logger.info(f"Загружены архивные данные за {month}/{year}: {len(archived_activities)} пользователей")
                return archived_activities
            else:
                logger.warning(f"Архивные данные за {month}/{year} не найдены или пусты")
                return {}
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке архивных данных: {e}", exc_info=True)
            return {}
    
    # НОВАЯ ЗАДАЧА: ежемесячный отчет
    @tasks.loop(time=time(hour=9, minute=0))  # 12:00 по МСК (UTC+3)
    async def monthly_report(self):
        """Отправляет ежемесячный отчет об активности всех пользователей за предыдущий месяц"""
        try:
            # Проверяем, что сегодня первое число месяца
            today = datetime.now()
            if today.day != 1:
                return
                
            logger.info("Начинаем формирование ежемесячного отчета за предыдущий месяц")
            
            # Определяем предыдущий месяц и год
            if today.month == 1:
                prev_month = 12
                prev_year = today.year - 1
            else:
                prev_month = today.month - 1
                prev_year = today.year
                
            # Проверяем существование архивного файла
            archive_filename = f"activity_{prev_year}_{prev_month:02d}.json"
            archive_path = os.path.join(self.archive_dir, archive_filename)
            
            if not os.path.exists(archive_path) or os.path.getsize(archive_path) == 0:
                logger.warning(f"Архивный файл за {prev_month}/{prev_year} не найден или пуст")
                return
                
            # Загружаем архивные данные
            with open(archive_path, "r", encoding="utf-8") as f:
                archived_data = json.load(f)
                
            # Проверяем, что есть данные
            if not archived_data:
                logger.warning(f"Нет данных об активности за {prev_month}/{prev_year}")
                return
                
            # Получаем месяц в текстовом виде
            month_names = {
                1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 
                5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
                9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
            }
            month_name = month_names.get(prev_month, f"Месяц {prev_month}")
            
            # Формируем канал для отправки
            channel = self.bot.get_channel(573665353327181824)  # канал cybersport
            
            if not channel:
                logger.error(f"Канал cybersport (ID: 573665353327181824) не найден")
                return
                
            # Подготавливаем данные - преобразуем строковые ключи в целые числа
            data = {}
            for user_id_str, activities in archived_data.items():
                user_id = int(user_id_str)
                filtered_activities = {game: time for game, time in activities.items() if time > 0}
                if filtered_activities:
                    data[user_id] = filtered_activities
                    
            # Если нет данных после фильтрации, прекращаем
            if not data:
                await channel.send(f"Нет данных об активности за {month_name} {prev_year} 😢")
                return
                
            # Формируем заголовок сообщения
            header = f"# 📊 Ежемесячный отчет за {month_name} {prev_year}\n\n"
            
            # Формируем содержимое по пользователям
            content = "## 👤 Активность всех пользователей\n"
            
            # Получаем сервер
            guild = channel.guild
            
            # Сортируем пользователей по игровому времени (общему)
            def get_total_time(user_data):
                return sum(user_data.values())
                
            sorted_users = sorted(data.items(), key=lambda x: get_total_time(x[1]), reverse=True)
            
            # Формируем строки для каждого пользователя
            for user_id, activities in sorted_users:
                # Получаем имя пользователя
                member = guild.get_member(user_id)
                username = member.name if member else f"Пользователь {user_id}"
                
                # Общее время пользователя
                total_time = get_total_time(activities)
                
                content += f"**{username}** (всего: {self.format_time(total_time)}): "
                
                # Сортируем активности по времени
                sorted_activities = sorted(activities.items(), key=lambda x: x[1], reverse=True)
                
                # Добавляем только игры с ненулевым временем
                games_list = [
                    f"{game_name} ({self.format_time_short(time_spent)})" 
                    for game_name, time_spent in sorted_activities 
                    if time_spent > 0
                ]
                
                content += ", ".join(games_list) + "\n\n"  # Двойной перенос для лучшей читаемости
            
            # Добавляем общую статистику
            content += self._get_monthly_summary(data, prev_month, prev_year)
            
            # Разбиваем сообщение, если оно слишком длинное (лимит Discord - 2000 символов)
            if len(header + content) <= 2000:
                await channel.send(header + content)
            else:
                # Отправляем заголовок отдельно
                await channel.send(header)
                
                # Разбиваем контент на части по 2000 символов
                chunks = [content[i:i+1990] for i in range(0, len(content), 1990)]
                for chunk in chunks:
                    await channel.send(chunk)
                    # Небольшая задержка между сообщениями, чтобы избежать рейт-лимитов
                    await asyncio.sleep(1)
            
            logger.info(f"Отправлен ежемесячный отчет за {month_name} {prev_year}")
                
        except Exception as e:
            logger.error(f"Ошибка при отправке ежемесячного отчета: {e}", exc_info=True)
            
    @monthly_report.before_loop
    async def before_monthly_report(self):
        """Ожидает готовности бота перед запуском задачи"""
        await self.bot.wait_until_ready()
        logger.info("Запущена задача ежемесячного отчета об активности")
        
    # НОВЫЙ МЕТОД: для ежемесячных отчетов
    def _get_monthly_summary(self, data, month, year):
        """Возвращает общую статистику для месячного отчета"""
        # Общее количество активных пользователей
        total_users = len(data)
        
        # Общее количество уникальных игр
        all_games = set()
        for user_data in data.values():
            all_games.update(user_data.keys())
        total_games = len(all_games)
        
        # Самая популярная игра (по количеству игроков)
        game_players = defaultdict(int)
        game_time = defaultdict(int)
        
        for user_data in data.values():
            for game, time_spent in user_data.items():
                game_players[game] += 1
                game_time[game] += time_spent
        
        # Найти самую популярную игру по количеству игроков
        most_played_game = max(game_players.items(), key=lambda x: x[1], default=("Нет данных", 0))
        
        # Найти игру с наибольшим временем
        most_time_game = max(game_time.items(), key=lambda x: x[1], default=("Нет данных", 0))
        
        # Общее время всех игроков
        total_time = sum(sum(user_data.values()) for user_data in data.values())
        
        # Формируем текст общей статистики
        summary = f"## 📊 Общая статистика за {month}/{year}\n"
        summary += f"👥 Всего активных игроков: **{total_users}**\n"
        summary += f"🎮 Уникальных игр: **{total_games}**\n"
        summary += f"⏱️ Общее время в играх: **{self.format_time(total_time)}**\n\n"
        
        # Добавляем информацию о популярных играх
        if most_played_game[0] != "Нет данных":
            summary += f"🏆 Самая популярная игра: **{most_played_game[0]}** ({most_played_game[1]} игроков)\n"
            
        if most_time_game[0] != "Нет данных" and most_time_game[0] != most_played_game[0]:
            summary += f"⭐ Игра с наибольшим временем: **{most_time_game[0]}** ({self.format_time(most_time_game[1])})\n"
        
        return summary
    
    @tasks.loop(time=time(hour=21, minute=0))  # 00:00 по МСК (UTC+3)
    async def daily_report(self):
        """Отправляет ежедневный отчет об активности пользователей"""
        try:
            logger.info("Начинаем формирование ежедневного отчета")
            
            # Обновляем данные для текущих активностей
            self.update_current_activities()
            
            # Формируем отчет
            channel = self.bot.get_channel(573665353327181824)  # канал cybersport
            
            if not channel:
                logger.error(f"Канал cybersport (ID: 573665353327181824) не найден")
                return
            
            # Фильтруем данные перед созданием представления
            daily_data = self.filter_zero_values(self.user_activities)
            
            # Если нет ДНЕВНЫХ данных после фильтрации, отправляем короткое сообщение
            if not daily_data:
                await channel.send("Сегодня никто не играл в игры 😢")
                logger.info("Нет данных об активности для отчета")
                return
            
            # Создаем интерактивное представление с отфильтрованными данными
            view = ActivityView(self, daily_data, report_type="daily")
            
            # Отправляем отчет
            message = await channel.send(content=view.get_current_content(), view=view)
            view.message = message
            
            logger.info(f"Отправлен ежедневный отчет об активности пользователей")
            
            # Сохраняем месячные данные перед сбросом дневных
            self.save_monthly_data()
            
            # Сбрасываем ТОЛЬКО дневные данные, месячные остаются!
            self.user_activities = {}
            self.save_data()
            logger.info("Дневные данные сброшены для нового дня")
            
        except Exception as e:
            logger.error(f"Ошибка при отправке ежедневного отчета: {e}", exc_info=True)
    
    @daily_report.before_loop
    async def before_daily_report(self):
        """Ожидает готовности бота перед запуском задачи"""
        await self.bot.wait_until_ready()
        logger.info("Запущена задача ежедневного отчета об активности")
    
    @commands.hybrid_command(description='Показать текущую статистику игровой активности или тест отчета')
    @commands.has_permissions(administrator=True)  # Только для администраторов
    async def activity(self, ctx, test_mode: bool = False):
        """Показывает текущую статистику игровой активности с опцией тестового режима"""
        try:
            # Обновляем данные для текущих активностей
            self.update_current_activities()
            
            # Фильтруем данные
            filtered_data = self.filter_zero_values(self.user_activities)
            
            # Если нет данных и включен тестовый режим, создаем тестовые данные
            if not filtered_data and test_mode:
                # Создаем тестовые данные
                filtered_data = {
                    ctx.author.id: {
                        "Genshin Impact": 3600 + 300,  # 1h5m
                        "Dota 2": 7200 + 1800,  # 2h30m
                    }
                }
                
                # Добавляем данные для нескольких других участников сервера
                for i, member in enumerate(list(ctx.guild.members)[:5]):
                    if member.id != ctx.author.id and not member.bot and not self.is_application(member):
                        games = {
                            "Minecraft": 1800 + 600 + i*300,  # 30m + 10m + variable
                            "Fortnite": 3600 + i*600,  # 1h + variable
                            "CS:GO": 5400 + i*300  # 1h30m + variable
                        }
                        filtered_data[member.id] = games
            elif not filtered_data:
                await ctx.send("Сегодня пока никто не играл в игры 😢")
                return
            
            # Создаем представление
            view = ActivityView(self, filtered_data, ctx=ctx, report_type="daily" if test_mode else "command")
            
            # Отправляем отчет
            prefix = "**[ТЕСТ]** Так будет выглядеть ежедневный отчет:\n\n" if test_mode else ""
            message = await ctx.send(content=f"{prefix}{view.get_current_content()}", view=view)
            view.message = message
            
        except Exception as e:
            logger.error(f"Ошибка при показе статистики активности: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")
    
    # ОБНОВЛЕННАЯ КОМАНДА: mystats с пагинацией
    @commands.hybrid_command(description='Показать статистику игровой активности пользователя')
    async def mystats(self, ctx, user: discord.Member = None, month: int = None, year: int = None):
        """Показывает статистику игровой активности пользователя за месяц с пагинацией"""
        try:
            # Если пользователь не указан, используем автора команды
            target_user = user if user else ctx.author
            user_id = target_user.id
            
            # Определяем, какие данные использовать
            if month is not None and year is not None:
                # Если указаны месяц и год, берем архивные данные
                data = self.load_archived_data(year, month)
                data_type = f"за {month}/{year}"
            else:
                # Иначе используем текущие месячные данные
                self.update_current_activities()  # Обновляем текущие активности
                data = self.filter_zero_values(self.monthly_activities)
                data_type = "за текущий месяц"
            
            # Проверяем, есть ли данные для пользователя
            if user_id not in data or not data[user_id]:
                embed = discord.Embed(
                    title=f"📊 Статистика {target_user.name}",  # Используем глобальное имя
                    description=f"Нет данных об активности {data_type} 😢",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                embed.set_thumbnail(url=target_user.display_avatar.url)
                await ctx.send(embed=embed)
                return
            
            # Берем уже отфильтрованные данные и сортируем
            user_games = data[user_id]
            sorted_games = sorted(user_games.items(), key=lambda x: x[1], reverse=True)
            
            # Создаем заголовок - используем глобальное имя вместо серверного
            title = f"📊 Статистика {target_user.name} {data_type}"
            
            # Создаем представление для пагинации (5 игр на страницу)
            view = StatsView(self, title, sorted_games, user=target_user, items_per_page=5)
            
            # Отправляем первую страницу
            message = await ctx.send(embed=view.get_current_embed(), view=view)
            view.message = message
            
            # Добавляем информацию о текущей активности, если она есть
            if month is None and year is None and user_id in self.current_activities:
                game_name, start_time = self.current_activities[user_id]
                now = datetime.now(pytz.UTC)
                current_session = int((now - start_time).total_seconds())
                if current_session > 0:  # Проверяем, что время > 0
                    # Отправляем отдельным сообщением информацию о текущей сессии
                    current_info = f"🔴 **{target_user.name}** сейчас играет в **{game_name}** ({self.format_time_short(current_session)})"
                    await ctx.send(current_info)
        
        except Exception as e:
            logger.error(f"Ошибка при отображении персональной статистики: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")
    
    @commands.hybrid_command(name="mystatsall", description="Показывает статистику пользователя за всё время")
    async def mystatsall(self, ctx, user: discord.Member = None):
        """Показывает статистику игровой активности пользователя за всё время с пагинацией"""
        try:
            # Если пользователь не указан, используем автора команды
            target_user = user if user else ctx.author
            user_id = target_user.id
            
            # Обновляем данные для текущих активностей
            self.update_current_activities()
            
            # Объединяем данные из текущего месяца и всех архивов для конкретного пользователя
            all_user_games = {}
            
            # 1. Добавляем данные из текущего месяца
            current_month_data = self.filter_zero_values(self.monthly_activities)
            if user_id in current_month_data:
                for game_name, time_spent in current_month_data[user_id].items():
                    if game_name not in all_user_games:
                        all_user_games[game_name] = 0
                    all_user_games[game_name] += time_spent
            
            # 2. Сканируем архивную директорию и добавляем данные пользователя из всех архивов
            for filename in os.listdir(self.archive_dir):
                if filename.endswith('.json') and filename.startswith('activity_'):
                    try:
                        # Извлекаем год и месяц из имени файла
                        parts = filename[:-5].split('_')  # Отрезаем .json
                        if len(parts) >= 3:
                            year = int(parts[1])
                            month = int(parts[2])
                            
                            # Загружаем архивные данные
                            archived_data = self.load_archived_data(year, month)
                            
                            # Добавляем данные пользователя, если они есть
                            if user_id in archived_data:
                                for game_name, time_spent in archived_data[user_id].items():
                                    if game_name not in all_user_games:
                                        all_user_games[game_name] = 0
                                    all_user_games[game_name] += time_spent
                    except Exception as e:
                        logger.error(f"Ошибка при обработке архивного файла {filename}: {e}", exc_info=True)
            
            # Сортируем игры по времени (убывание)
            sorted_games = sorted(all_user_games.items(), key=lambda x: x[1], reverse=True)
            
            # Если данных нет, сообщаем об этом
            if not sorted_games:
                embed = discord.Embed(
                    title=f"📊 Статистика {target_user.name}",  # Используем глобальное имя
                    description=f"Нет данных об активности за всё время 😢",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                embed.set_thumbnail(url=target_user.display_avatar.url)
                await ctx.send(embed=embed)
                return
            
            # Создаем заголовок - используем глобальное имя
            title = f"📊 Статистика {target_user.name} за всё время"
            
            # Создаем представление для пагинации (10 игр на страницу для mystatsall)
            view = StatsView(self, title, sorted_games, user=target_user, items_per_page=10, all_time=True)
            
            # Отправляем первую страницу
            message = await ctx.send(embed=view.get_current_embed(), view=view)
            view.message = message
            
        except Exception as e:
            logger.error(f"Ошибка при выполнении команды mystatsall: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")
    
    # Обработчики ошибок команд
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
        """Обработчик ошибок для команды mystatsall"""
        if isinstance(error, commands.UserNotFound):
            await ctx.send("Не удалось найти указанного пользователя. Проверьте правильность имени или ID.", ephemeral=True)
        else:
            logger.error(f"Ошибка в команде mystatsall: {error}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {error}", ephemeral=True)

async def setup(bot):
    """Загружает ког ActivityTracker"""
    await bot.add_cog(ActivityTracker(bot))
