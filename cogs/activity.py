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

logger = logging.getLogger("bot")

class ActivityTracker(commands.Cog):
    """Отслеживает игровую активность пользователей на сервере"""
    
    def __init__(self, bot):
        self.bot = bot
        
        # Используем абсолютный путь к файлу
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_file = os.path.join(base_dir, "data", "user_activities.json")
        
        logger.info(f"Инициализация ActivityTracker")
        
        # Создаем директорию при инициализации
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        
        self.user_activities = {}  # user_id -> {game_name: total_seconds}
        self.current_activities = {}  # user_id -> (game_name, start_time)
        
        self.load_data()
        
        # Запуск задач
        self.daily_report.start()
        self.periodic_save.start()
        
        # Задача для сканирования активности всех пользователей после запуска
        self.bot.loop.create_task(self.scan_all_users_activity())
    
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
                    
                    # Проверяем, играет ли пользователь в игру
                    if member.activity and member.activity.type == discord.ActivityType.playing:
                        game_name = member.activity.name
                        logger.info(f"Обнаружена активная игра у пользователя {member.name}: {game_name}")
                        
                        # Добавляем в текущие активности
                        self.current_activities[member.id] = (game_name, now)
            
            logger.info(f"Сканирование завершено. Обнаружено {len(self.current_activities)} активных игроков.")
            
            # Сохраняем данные после сканирования
            if self.current_activities:
                self.save_data()
        
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
        self.daily_report.cancel()
        self.periodic_save.cancel()
        
        # Сохраняем данные при выгрузке кога
        self.update_current_activities()
        self.save_data()
        logger.info("ActivityTracker выгружен, данные сохранены")
    
    def load_data(self):
        """Загружает данные об активности из файла"""
        try:
            if os.path.exists(self.data_file):
                # Проверяем, что файл не пустой
                if os.path.getsize(self.data_file) > 0:
                    logger.info(f"Загрузка данных об активности из файла")
                    with open(self.data_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # Преобразуем строковые ключи обратно в числа
                    self.user_activities = {int(user_id): activities 
                                        for user_id, activities in data.items()}
                    
                    logger.info(f"Загружены данные об активности пользователей: {len(self.user_activities)} пользователей")
                else:
                    logger.info(f"Файл данных пустой, создаем пустой словарь")
                    self.user_activities = {}
            else:
                logger.info(f"Файл данных об активности не найден, создан пустой словарь")
                self.user_activities = {}
                
                # Создаем пустой файл
                with open(self.data_file, "w", encoding="utf-8") as f:
                    json.dump({}, f)
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке данных об активности: {e}", exc_info=True)
            self.user_activities = {}
    
    def save_data(self):
        """Сохраняет данные об активности в файл"""
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
                logger.info(f"Данные об активности пользователей успешно сохранены")
            else:
                logger.warning(f"Временный файл пустой, не переименовываем")
                os.remove(temp_file)
                
        except Exception as e:
            logger.error(f"Ошибка при сохранении данных об активности: {e}", exc_info=True)
    
    def reset_daily_data(self):
        """Сбрасывает данные об активности на текущий день"""
        self.user_activities = {}
        self.save_data()
        logger.info("Данные об активности сброшены")
    
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
    
    def update_current_activities(self):
        """Обновляет статистику для текущих активностей"""
        now = datetime.now(pytz.UTC)
        for user_id, (game_name, start_time) in list(self.current_activities.items()):
            # Вычисляем проведенное время
            elapsed_seconds = int((now - start_time).total_seconds())
            
            # Обновляем статистику только если прошло некоторое время (чтобы избежать шума от частых обновлений)
            if elapsed_seconds < 10:  # Минимальный порог в секундах
                continue
                
            # Обновляем статистику
            if user_id not in self.user_activities:
                self.user_activities[user_id] = {}
            
            if game_name not in self.user_activities[user_id]:
                self.user_activities[user_id][game_name] = elapsed_seconds
            else:
                self.user_activities[user_id][game_name] += elapsed_seconds
            
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
            
            # Игра до обновления
            before_game = None
            if before.activity and before.activity.type == discord.ActivityType.playing:
                before_game = before.activity.name
            
            # Игра после обновления
            after_game = None
            if after.activity and after.activity.type == discord.ActivityType.playing:
                after_game = after.activity.name
            
            # Если статус игры не изменился, пропускаем
            if before_game == after_game:
                return
                
            # Логируем изменение только при реальных изменениях статуса игры
            if before_game != after_game:
                logger.debug(f"Изменение активности пользователя {after.name}: {before_game} -> {after_game}")
            
            # Обрабатываем начало игры
            if before_game is None and after_game is not None:
                # Пользователь начал играть в игру
                self.current_activities[user_id] = (after_game, now)
                logger.debug(f"Пользователь {after.name} начал играть в {after_game}")
            
            # Обрабатываем изменение игры
            elif before_game is not None and after_game is not None and before_game != after_game:
                # Пользователь сменил игру
                if user_id in self.current_activities:
                    game_name, start_time = self.current_activities[user_id]
                    
                    # Вычисляем проведенное время
                    elapsed_seconds = int((now - start_time).total_seconds())
                    
                    # Обновляем статистику
                    if user_id not in self.user_activities:
                        self.user_activities[user_id] = {}
                    
                    if game_name not in self.user_activities[user_id]:
                        self.user_activities[user_id][game_name] = elapsed_seconds
                    else:
                        self.user_activities[user_id][game_name] += elapsed_seconds
                    
                    logger.debug(f"Пользователь {after.name} играл в {game_name} {self.format_time(elapsed_seconds)}")
                
                # Обновляем текущую активность
                self.current_activities[user_id] = (after_game, now)
                logger.debug(f"Пользователь {after.name} начал играть в {after_game}")
            
            # Обрабатываем завершение игры
            elif before_game is not None and after_game is None:
                # Пользователь перестал играть
                if user_id in self.current_activities:
                    game_name, start_time = self.current_activities[user_id]
                    
                    # Вычисляем проведенное время
                    elapsed_seconds = int((now - start_time).total_seconds())
                    
                    # Обновляем статистику
                    if user_id not in self.user_activities:
                        self.user_activities[user_id] = {}
                    
                    if game_name not in self.user_activities[user_id]:
                        self.user_activities[user_id][game_name] = elapsed_seconds
                    else:
                        self.user_activities[user_id][game_name] += elapsed_seconds
                    
                    # Удаляем текущую активность
                    del self.current_activities[user_id]
                    
                    logger.debug(f"Пользователь {after.name} закончил играть в {game_name}, общее время: {self.format_time(elapsed_seconds)}")
                    
                    # Сохраняем данные при завершении игры
                    self.save_data()
        
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
        except Exception as e:
            logger.error(f"Ошибка при периодическом сохранении: {e}", exc_info=True)
    
    @periodic_save.before_loop
    async def before_periodic_save(self):
        """Ожидает готовности бота перед запуском задачи"""
        await self.bot.wait_until_ready()
        logger.info("Запущена задача периодического сохранения данных об активности")
    
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
            
            # Если нет данных, отправляем короткое сообщение
            if not self.user_activities:
                await channel.send("Сегодня никто не играл в игры 😢")
                logger.info("Нет данных об активности для отчета")
                return
            
            # Создаем эмбед для отчета
            embed = discord.Embed(
                title="📊 Ежедневный отчет об игровой активности",
                description=f"Статистика за {datetime.now().strftime('%d.%m.%Y')}",
                color=discord.Color.blue()
            )
            
            # Добавляем данные по каждому пользователю
            for user_id, activities in self.user_activities.items():
                try:
                    # Получаем объект пользователя
                    user = channel.guild.get_member(user_id)
                    if not user or user.bot or self.is_application(user):
                        # Пропускаем пользователей, которых нет на сервере или ботов/приложения
                        continue
                    
                    # Формируем строку с играми
                    activities_str = []
                    for game_name, seconds in sorted(activities.items(), key=lambda x: x[1], reverse=True):
                        activities_str.append(f"{game_name}: {self.format_time(seconds)}")
                    
                    # Если есть активность, добавляем в эмбед
                    if activities_str:
                        embed.add_field(
                            name=user.display_name,
                            value="\n".join(activities_str),
                            inline=True
                        )
                except Exception as e:
                    logger.error(f"Ошибка при обработке пользователя {user_id}: {e}", exc_info=True)
            
            # Добавляем общую статистику
            total_users = len([uid for uid in self.user_activities if channel.guild.get_member(uid) and 
                              not channel.guild.get_member(uid).bot and 
                              not self.is_application(channel.guild.get_member(uid))])
            
            all_games = set()
            for uid, activities in self.user_activities.items():
                user = channel.guild.get_member(uid)
                if user and not user.bot and not self.is_application(user):
                    all_games.update(activities.keys())
            
            # Находим самую популярную игру
            game_counts = defaultdict(int)
            for uid, activities in self.user_activities.items():
                user = channel.guild.get_member(uid)
                if user and not user.bot and not self.is_application(user):
                    for game in activities:
                        game_counts[game] += 1
            
            most_popular_game = max(game_counts.items(), key=lambda x: x[1], default=(None, 0))
            
            embed.add_field(
                name="📈 Общая статистика",
                value=f"Всего игроков: {total_users}\n"
                      f"Уникальных игр: {len(all_games)}\n"
                      f"Самая популярная игра: {most_popular_game[0]} ({most_popular_game[1]} игроков)" if most_popular_game[0] else "Нет данных",
                inline=False
            )
            
            embed.set_footer(text="Статистика сбрасывается каждый день в 00:00 по МСК")
            
            # Отправляем отчет
            await channel.send(embed=embed)
            logger.info(f"Отправлен ежедневный отчет об активности пользователей")
            
            # Сбрасываем данные на новый день
            self.reset_daily_data()
            
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
            
            # Если нет данных, отправляем короткое сообщение
            if not self.user_activities:
                await ctx.send("Сегодня пока никто не играл в игры 😢")
                return
            
            # Создаем эмбед для отчета
            embed = discord.Embed(
                title="📊 Статистика игровой активности",
                description=f"Данные на {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                color=discord.Color.blue()
            )
            
            # Добавляем данные по каждому пользователю
            for user_id, activities in self.user_activities.items():
                try:
                    # Получаем объект пользователя
                    user = ctx.guild.get_member(user_id)
                    if not user or user.bot or self.is_application(user):
                        # Пропускаем пользователей, которых нет на сервере или ботов/приложения
                        continue
                    
                    # Формируем строку с играми
                    activities_str = []
                    for game_name, seconds in sorted(activities.items(), key=lambda x: x[1], reverse=True):
                        activities_str.append(f"{game_name}: {self.format_time(seconds)}")
                    
                    # Если есть активность, добавляем в эмбед
                    if activities_str:
                        embed.add_field(
                            name=user.display_name,
                            value="\n".join(activities_str),
                            inline=True
                        )
                except Exception as e:
                    logger.error(f"Ошибка при обработке пользователя {user_id}: {e}")
            
            # Добавляем инфо о текущем отчете
            embed.set_footer(text="Используйте /activity для просмотра текущей статистики (только для администраторов)")
            
            # Отправляем отчет
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Ошибка при показе статистики активности: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")
    
    # Обработчик ошибки отсутствия прав доступа
    @activity.error
    async def activity_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас недостаточно прав для использования этой команды. Требуются права администратора.", ephemeral=True)
        else:
            logger.error(f"Ошибка в команде activity: {error}", exc_info=True)
            await ctx.send(f"Произошла ошибка: {error}", ephemeral=True)

async def setup(bot):
    """Загружает ког ActivityTracker"""
    await bot.add_cog(ActivityTracker(bot))