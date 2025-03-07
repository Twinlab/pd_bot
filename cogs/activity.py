class ActivityView(ui.View):
    """Интерактивное представление статистики активности с кнопками"""
    
    def __init__(self, cog, data, ctx=None, report_type="daily"):
        super().__init__(timeout=300)  # 5 минут таймаут
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
        
        # Используем абсолютный путь к файлу
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_file = os.path.join(base_dir, "data", "user_activities.json")
        
        logger.info(f"Инициализация ActivityTracker")
        
        # Создаем директорию при инициализации
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        
        self.user_activities = {}  # user_id -> {game_name: total_seconds}
        self.current_activities = {}  # user_id -> (game_name, start_time)
        
        self.load_data()
        
        # Планируем сканирование активности на потом
        self.scan_scheduled = False
        
        # Запуск задач
        self.daily_report.start()
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
            
            # Создаем интерактивное представление
            view = ActivityView(self, self.user_activities, report_type="daily")
            
            # Отправляем отчет
            message = await channel.send(content=view.get_current_content(), view=view)
            view.message = message
            
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
            
            # Создаем интерактивное представление
            view = ActivityView(self, self.user_activities, ctx=ctx, report_type="command")
            
            # Отправляем отчет
            message = await ctx.send(content=view.get_current_content(), view=view)
            view.message = message
            
        except Exception as e:
            logger.error(f"Ошибка при показе статистики активности: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}")

    @commands.hybrid_command(description='Протестировать формат ежедневного отчета')
    @commands.has_permissions(administrator=True)  # Только для администраторов
    async def test_report(self, ctx):
        """Тестирует формат ежедневного отчета"""
        try:
            logger.info("Запуск тестирования формата ежедневного отчета")
            
            # Обновляем данные для текущих активностей перед генерацией отчета
            self.update_current_activities()
            
            # Если нет реальных данных, создаем тестовые данные
            test_data = {}
            for user_id, activities in self.user_activities.items():
                # Копируем только активности с ненулевым временем
                filtered = {game: time for game, time in activities.items() if time > 0}
                if filtered:
                    test_data[user_id] = filtered
            
            if not test_data:
                logger.info("Создание тестовых данных для отчета")
                # Создаем тестовые данные
                test_data = {
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
                        test_data[member.id] = games
            
            # Создаем интерактивное представление с тестовыми данными
            view = ActivityView(self, test_data, ctx=ctx, report_type="daily")
            
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

