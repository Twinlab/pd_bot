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
        super().__init__(timeout=1800)  # 30 минут таймаут
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
            # Отфильтровываем только активности с временем > 0
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
        for user_id, activities in self.data.items():
            for game, time in activities.items():
                if time > 0:  # Только активности с временем > 0
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
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if hours > 0:
            if minutes > 0:
                return f"{hours}h {minutes}m"
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
            
            # Добавляем каждую игру в одну строку
            games_list = [f"{game_name} ({self.format_time_short(time_spent)})" for game_name, time_spent in activities]
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
        self.periodic_save.start()
    
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
                    json.dump({}, f, indent=2)
                    
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
                    
                    # Преобразуем строковые ключи обратно в числа
                    self.user_activities = {int(user_id): activities 
                                        for user_id, activities in data.items()}
                    
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
                    
                    # Преобразуем строковые ключи обратно в числа
                    self.monthly_activities = {int(user_id): activities 
                                           for user_id, activities in data.items()}
                    
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
            
            # Сначала записываем во временный файл
            temp_file = f"{self.data_file}.tmp"
            
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.user_activities, f, indent=2)
            
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
            
            # Сначала записываем во временный файл
            temp_file = f"{self.monthly_file}.tmp"
            
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.monthly_activities, f, indent=2)
            
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
        """Форматирует время в секундах в краткую строку (1h5m)"""
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if hours > 0:
            if minutes > 0:
                return f"{hours}h{minutes}m"
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
            
            # Обновляем статистику только если прошло некоторое время
            if elapsed_seconds < 10:  # Минимальный порог в секундах
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
            
            # Копируем месячные данные в архив
            if os.path.exists(self.monthly_file) and os.path.getsize(self.monthly_file) > 0:
                import shutil
                shutil.copy2(self.monthly_file, archive_path)
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
                
                # Преобразуем строковые ключи обратно в числа
                archived_activities = {int(user_id): activities 
                                    for user_id, activities in data.items()}
                
                logger.info(f"Загружены архивные данные за {month}/{year}: {len(archived_activities)} пользователей")
                return archived_activities
            else:
                logger.warning(f"Архивные данные за {month}/{year} не найдены или пусты")
                return {}
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке архивных данных: {e}", exc_info=True)
            return {}
    
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
            
            # Если нет ДНЕВНЫХ данных, отправляем короткое сообщение
            if not self.user_activities:
                await channel.send("Сегодня никто не играл в игры 😢")
                logger.info("Нет данных об активности для отчета")
                return
            
            # Создаем копию данных перед очисткой
            daily_data = {}
            for user_id, games in self.user_activities.items():
                # Копируем только ненулевые активности
                filtered_games = {game: time for game, time in games.items() if time > 0}
                if filtered_games:
                    daily_data[user_id] = filtered_games
            
            # Создаем интерактивное представление с ДНЕВНЫМИ данными
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
    
    @commands.hybrid_command(description='Показать текущую статистику игровой активности')
    @commands.has_permissions(administrator=True)  # Только для администраторов
    async def activity(self, ctx):
        """Показывает текущую статистику игровой активности"""
        try:
            # Обновляем данные для текущих активностей
            self.update_current_activities()
            
            # Если нет ДНЕВНЫХ данных, отправляем короткое сообщение
            if not self.user_activities:
                await ctx.send("Сегодня пока никто не играл в игры 😢")
                return
            
            # Создаем копию данных с фильтрацией нулевых значений
            filtered_data = {}
            for user_id, games in self.user_activities.items():
                filtered_games = {game: time for game, time in games.items() if time > 0}
                if filtered_games:
                    filtered_data[user_id] = filtered_games
            
            # Создаем интерактивное представление с ДНЕВНЫМИ данными
            view = ActivityView(self, filtered_data, ctx=ctx, report_type="command")
            
            # Отправляем отчет
            message = await ctx.send(content=view.get_current_content(), view=view)
            view.message = message
            
        except Exception as e:
            logger.error(f"Ошибка при показе статистики активности: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")
    
    @commands.hybrid_command(description='Показать статистику игровой активности пользователя')
    async def mystats(self, ctx, user: discord.Member = None, month: int = None, year: int = None):
        """Показывает статистику игровой активности пользователя за месяц"""
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
                data = self.monthly_activities
                data_type = "за текущий месяц"
            
            # Создаем эмбед
            embed = discord.Embed(
                title=f"📊 Статистика игрока {target_user.display_name}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Устанавливаем аватар пользователя
            embed.set_thumbnail(url=target_user.display_avatar.url)
            
            # Проверяем, есть ли данные для пользователя
            if user_id not in data or not data[user_id]:
                embed.description = f"Нет данных об активности {data_type} 😢"
                await ctx.send(embed=embed)
                return
            
            # Сортируем игры по времени (от большего к меньшему)
            user_games = data[user_id]
            # Фильтруем только ненулевые значения
            filtered_games = {game: time for game, time in user_games.items() if time > 0}
            sorted_games = sorted(filtered_games.items(), key=lambda x: x[1], reverse=True)
            
            # Топ-5 игр
            top_games_text = ""
            for i, (game, time_spent) in enumerate(sorted_games[:5], 1):
                top_games_text += f"{i}. **{game}** - {self.format_time(time_spent)}\n"
            
            if top_games_text:
                embed.add_field(name="🏆 Топ игры", value=top_games_text, inline=False)
            
            # Общее игровое время
            total_time = sum(filtered_games.values())
            embed.add_field(name="⏱️ Всего в играх", value=self.format_time(total_time), inline=True)
            
            # Количество игр
            games_count = len(filtered_games)
            embed.add_field(name="🎮 Количество игр", value=str(games_count), inline=True)
            
            # Текущая активность (если смотрим текущий месяц)
            if month is None and year is None and user_id in self.current_activities:
                game_name, start_time = self.current_activities[user_id]
                now = datetime.now(pytz.UTC)
                current_session = int((now - start_time).total_seconds())
                embed.add_field(
                    name="🔴 Сейчас играет",
                    value=f"**{game_name}** ({self.format_time(current_session)})",
                    inline=False
                )
            
            # Подпись
            embed.set_footer(text=f"Статистика {data_type} • Для общей статистики: /activity")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Ошибка при отображении персональной статистики: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")

    @commands.hybrid_command(description='Показать архивную статистику за предыдущий месяц')
    @commands.has_permissions(administrator=True)  # Только для администраторов
    async def archived_stats(self, ctx, year: int = None, month: int = None):
        """Показывает архивную статистику за указанный месяц"""
        try:
            # Если год и месяц не указаны, берем предыдущий месяц
            if year is None or month is None:
                today = datetime.now()
                if today.month == 1:
                    year = today.year - 1
                    month = 12
                else:
                    year = today.year
                    month = today.month - 1
            
            # Проверка корректности даты
            if not (1 <= month <= 12 and year >= 2020):
                await ctx.send("Пожалуйста, укажите корректный месяц (1-12) и год (не ранее 2020)")
                return
            
            # Загружаем архивные данные
            archived_data = self.load_archived_data(year, month)
            
            if not archived_data:
                await ctx.send(f"Архивные данные за {month:02d}/{year} не найдены или пусты")
                return
            
            # Фильтруем данные (убираем нулевые значения)
            filtered_data = {}
            for user_id, games in archived_data.items():
                filtered_games = {game: time for game, time in games.items() if time > 0}
                if filtered_games:
                    filtered_data[user_id] = filtered_games
            
            # Создаем интерактивное представление с архивными данными
            view = ActivityView(self, filtered_data, ctx=ctx, report_type="command")
            
            # Формируем месяц в текстовом виде
            month_names = {
                1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 
                5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
                9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
            }
            month_name = month_names.get(month, f"Месяц {month}")
            
            # Отправляем отчет с указанием периода
            header = f"# 📊 Архивная статистика за {month_name} {year}\n\n"
            content = view.get_current_content().replace("# 📊 Статистика", header)
            
            message = await ctx.send(content=content, view=view)
            view.message = message
            
        except Exception as e:
            logger.error(f"Ошибка при показе архивной статистики: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении архивной статистики: {e}")

    @commands.hybrid_command(description='Протестировать формат ежедневного отчета')
    @commands.has_permissions(administrator=True)  # Только для администраторов
    async def test_report(self, ctx):
        """Тестирует формат ежедневного отчета на основе текущей дневной статистики"""
        try:
            logger.info("Запуск тестирования формата ежедневного отчета")
            
            # Обновляем данные для текущих активностей перед генерацией отчета
            self.update_current_activities()
            
            # Фильтруем дневные данные (убираем записи с нулевым временем)
            filtered_data = {}
            for user_id, games in self.user_activities.items():
                filtered_games = {game: time for game, time in games.items() if time > 0}
                if filtered_games:
                    filtered_data[user_id] = filtered_games
            
            # Если нет реальных данных, создаем тестовые данные
            if not filtered_data:
                logger.info("Создание тестовых данных для отчета")
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
            
            # Создаем интерактивное представление с данными
            view = ActivityView(self, filtered_data, ctx=ctx, report_type="daily")
            
            # Отправляем тестовый отчет
            message = await ctx.send(
                content=f"**[ТЕСТ]** Так будет выглядеть ежедневный отчет:\n\n{view.get_current_content()}", 
                view=view
            )
            view.message = message
            
            logger.info(f"Тестовый отчет об активности отправлен")
            
        except Exception as e:
            logger.error(f"Ошибка при тестировании отчета: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при создании тестового отчета: {e}")
    
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
    
    @archived_stats.error
    async def archived_stats_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас недостаточно прав для использования этой команды. Требуются права администратора.", ephemeral=True)
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Неверный формат аргументов. Укажите год и месяц в числовом формате (например, 2023 12).", ephemeral=True)
        else:
            logger.error(f"Ошибка в команде archived_stats: {error}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {error}", ephemeral=True)
    
    @test_report.error
    async def test_report_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас недостаточно прав для использования этой команды. Требуются права администратора.", ephemeral=True)
        else:
            logger.error(f"Ошибка в команде test_report: {error}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {error}", ephemeral=True)

async def setup(bot):
    """Загружает ког ActivityTracker"""
    await bot.add_cog(ActivityTracker(bot))
