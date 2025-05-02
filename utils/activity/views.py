import discord
from discord import ui, ButtonStyle, Interaction
from discord.ext import commands  # Добавляем импорт commands из discord.ext
from datetime import datetime
from collections import defaultdict
from typing import Dict, Optional, Any, Union, List, Tuple # Добавляем List и Tuple

# Импортируем хелперы форматирования времени
from .helpers import format_time_short

# TODO: Рассмотреть возможность передачи format_time_short через __init__
#       вместо прямого импорта, если потребуется большая гибкость или тестирование.

class ActivityView(ui.View):
    """
    Интерактивное представление (View) для отображения статистики игровой активности.

    Позволяет переключаться между режимами "по пользователям" и "по играм",
    а также листать страницы с помощью кнопок.
    """

    def __init__(self, bot: discord.Client, data: Dict[int, Dict[str, int]], ctx: Optional[commands.Context] = None, report_type: str = "daily"):
        """
        Инициализирует представление статистики активности.

        Args:
            bot: Экземпляр бота Discord (для доступа к гильдиям/участникам).
            data: Словарь с данными активности {user_id: {game_name: seconds}}.
            ctx: Контекст команды (если вызвано командой, для получения гильдии).
            report_type: Тип отчета ("daily" для автоматического, "command" для ручного).
        """
        super().__init__(timeout=86400)  # 24 часа таймаут
        self.bot = bot
        self.data = data  # Все данные о активности (дневные или месячные)
        self.ctx = ctx
        self.report_type = report_type  # "daily" или "command"
        self.current_page = 0
        self.view_mode = "users"  # "users" или "games"
        self.max_items_per_page = 20
        self.message: Optional[discord.Message] = None # Для редактирования при таймауте

        # Подготавливаем данные для отображения
        self.prepare_data()

        # Сразу устанавливаем правильную надпись на кнопке переключения режима
        # и отключаем кнопки навигации, если страниц мало
        self._update_buttons()

    def _get_guild(self) -> Optional[discord.Guild]:
        """Получает объект гильдии из контекста или из кеша бота."""
        if self.ctx and self.ctx.guild:
            return self.ctx.guild
        # Если контекста нет (например, автоматический отчет), берем первую попавшуюся гильдию
        # Это может быть не идеально для многосерверных ботов, но для одного сервера подойдет.
        if self.bot.guilds:
            return self.bot.guilds[0]
        return None

    def prepare_data(self):
        """
        Подготавливает и сортирует данные для отображения в режимах "по пользователям" и "по играм".

        Фильтрует игры с нулевым временем. Рассчитывает максимальное количество страниц.
        """
        # Отображение по пользователям
        # Фильтруем пользователей и игры с нулевым временем
        self.users_data: Dict[int, Dict[str, int]] = {}
        for user_id, activities in self.data.items():
            filtered_activities = {game: time for game, time in activities.items() if time > 0}
            if filtered_activities:
                self.users_data[user_id] = filtered_activities

        # Создаем список ID пользователей, отсортированный по имени
        guild = self._get_guild()
        if not guild:
             # Если гильдию получить не удалось, сортируем просто по ID
             self.user_ids = sorted(self.users_data.keys())
        else:
            def get_username(user_id: int) -> str:
                member = guild.get_member(user_id)
                # Используем имя пользователя или ID, если участник не найден
                return member.name.lower() if member else f"user_{user_id}"
            # Сортируем пользователей по алфавиту
            self.user_ids = sorted(self.users_data.keys(), key=get_username)

        # Отображение по играм
        self.games_data: Dict[str, Dict[int, int]] = defaultdict(dict)
        for user_id, activities in self.users_data.items():
            for game, time in activities.items():
                # Дополнительная проверка > 0 не нужна, т.к. users_data уже отфильтрован
                self.games_data[game][user_id] = time

        # Создаем список игр, отсортированный по популярности (кол-во игроков, затем общее время)
        self.games_list = sorted(
            self.games_data.keys(),
            key=lambda g: (len(self.games_data[g]), sum(self.games_data[g].values())),
            reverse=True
        )

        # Считаем общее количество страниц для текущего режима
        self._recalculate_max_pages()

    def _recalculate_max_pages(self):
        """Пересчитывает максимальное количество страниц в зависимости от режима."""
        if self.view_mode == "users":
            count = len(self.user_ids)
        else: # view_mode == "games"
            count = len(self.games_list)
        self.max_pages = max(1, (count + self.max_items_per_page - 1) // self.max_items_per_page)
        # Сбрасываем на первую страницу при смене режима или если текущая страница стала невалидной
        if self.current_page >= self.max_pages:
            self.current_page = 0

    def _update_buttons(self):
        """Обновляет состояние кнопок (включены/выключены, текст)."""
        for item in self.children:
            if not isinstance(item, ui.Button):
                continue
            # Кнопка переключения режима
            if item.custom_id == "toggle_mode_button":
                 item.label = "По играм" if self.view_mode == "users" else "По пользователям"
            # Кнопки навигации
            elif item.custom_id == "prev_button":
                item.disabled = self.current_page == 0
            elif item.custom_id == "next_button":
                item.disabled = self.current_page >= self.max_pages - 1

    def get_current_content(self) -> str:
        """
        Формирует текстовое содержимое для текущей страницы и режима отображения.

        Returns:
            Строка с отформатированным отчетом для отправки в Discord.
        """
        report_title = 'Ежедневный отчет' if self.report_type == 'daily' else 'Статистика'
        header = f"# 📊 {report_title} игровой активности\n\n"

        if self.view_mode == "users":
            content = self._get_users_content()
        else: # view_mode == "games"
            content = self._get_games_content()

        # Добавляем общую статистику и номер страницы
        summary = self._get_summary()
        footer = f"\n*Страница {self.current_page + 1}/{self.max_pages}*"
        return header + content + "\n" + summary + footer

    def _get_users_content(self) -> str:
        """Формирует содержимое для режима отображения "по пользователям"."""
        content = "## 👤 По пользователям\n"
        start_idx = self.current_page * self.max_items_per_page
        end_idx = min(start_idx + self.max_items_per_page, len(self.user_ids))
        current_user_ids = self.user_ids[start_idx:end_idx]

        if not current_user_ids:
            return content + "*Нет данных для отображения на этой странице.*\n"

        guild = self._get_guild()
        for user_id in current_user_ids:
            member = guild.get_member(user_id) if guild else None
            username = member.name if member else f"Пользователь {user_id}"
            content += f"**{username}**: "

            # Сортируем игры пользователя по времени
            activities = sorted(
                self.users_data[user_id].items(),
                key=lambda item: item[1],
                reverse=True
            )
            # Формируем строку игр
            games_list = [
                f"{game_name} ({format_time_short(time_spent)})"
                for game_name, time_spent in activities
                # Доп. проверка > 0 не нужна, т.к. данные уже отфильтрованы в prepare_data
            ]
            content += ", ".join(games_list) + "\n"

        return content

    def _get_games_content(self) -> str:
        """Формирует содержимое для режима отображения "по играм"."""
        content = "## 🎮 По играм\n"
        start_idx = self.current_page * self.max_items_per_page
        end_idx = min(start_idx + self.max_items_per_page, len(self.games_list))
        current_games = self.games_list[start_idx:end_idx]

        if not current_games:
            return content + "*Нет данных для отображения на этой странице.*\n"

        for game_name in current_games:
            players_data = self.games_data[game_name]
            total_time = sum(players_data.values())
            players_count = len(players_data)

            # Пропускаем, если время нулевое (хотя такого быть не должно после фильтрации)
            if total_time <= 0:
                continue

            # Формируем информацию об игроках
            players_info = f"{players_count} {'игрока' if 2 <= players_count <= 4 else 'игроков'}" if players_count > 1 else "1 игрок"
            content += f"**{game_name}**: {players_info} ⏱️ {format_time_short(total_time)}\n"

        return content

    def _get_summary(self) -> str:
        """
        Формирует строку с общей статистикой (всего игроков, игр, времени, топ игра).

        Returns:
            Строка с общей статистикой.
        """
        total_users = len(self.users_data)
        total_games = len(self.games_data) # Используем games_data, т.к. там только игры с >0 временем

        most_popular_game: Optional[str] = None
        max_players = 0
        # Находим самую популярную игру по количеству игроков
        for game, players in self.games_data.items():
            if len(players) > max_players:
                max_players = len(players)
                most_popular_game = game

        # Считаем общее время
        total_time = sum(sum(user_activities.values()) for user_activities in self.users_data.values())

        # Формируем строку
        summary = f"## 📊 Общая статистика\n"
        summary += f"Всего игроков: {total_users} | "
        summary += f"Уникальных игр: {total_games} | "
        summary += f"Общее время: {format_time_short(total_time)}" # Используем краткий формат
        if most_popular_game:
            players_str = f"{max_players} {'игрока' if 2 <= max_players <= 4 else 'игроков'}" if max_players > 1 else "1 игрок"
            summary += f"\nСамая популярная игра: **{most_popular_game}** ({players_str})"
        return summary

    # --- Кнопки ---

    @ui.button(label="⬅️ Назад", style=ButtonStyle.gray, custom_id="prev_button")
    async def previous_button(self, interaction: Interaction, button: ui.Button):
        """Переключает на предыдущую страницу."""
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(content=self.get_current_content(), view=self)
        else:
            # Если уже на первой странице, ничего не делаем (кнопка должна быть disabled)
            await interaction.response.defer()

    @ui.button(label="По играм", style=ButtonStyle.blurple, custom_id="toggle_mode_button")
    async def toggle_mode(self, interaction: Interaction, button: ui.Button):
        """Переключает режим отображения (пользователи/игры)."""
        self.view_mode = "games" if self.view_mode == "users" else "users"
        self.current_page = 0 # Сбрасываем на первую страницу
        self._recalculate_max_pages() # Пересчитываем кол-во страниц для нового режима
        self._update_buttons() # Обновляем текст кнопки и состояние кнопок навигации
        await interaction.response.edit_message(content=self.get_current_content(), view=self)

    @ui.button(label="Вперед ➡️", style=ButtonStyle.gray, custom_id="next_button")
    async def next_button(self, interaction: Interaction, button: ui.Button):
        """Переключает на следующую страницу."""
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(content=self.get_current_content(), view=self)
        else:
            # Если уже на последней странице, ничего не делаем (кнопка должна быть disabled)
            await interaction.response.defer()

    async def on_timeout(self):
        """Отключает кнопки при истечении времени ожидания."""
        for item in self.children:
            if isinstance(item, (ui.Button, ui.Select)):
                item.disabled = True
        if self.message:
            try:
                # Пытаемся отредактировать исходное сообщение, чтобы показать неактивные кнопки
                await self.message.edit(view=self)
            except discord.HTTPException:
                # Игнорируем ошибки, если сообщение было удалено или недоступно
                pass

# --- Представление для /mystats и /mystatsall ---

class StatsView(ui.View):
    """
    Интерактивное представление (View) для пагинации статистики игр пользователя
    (используется командами /mystats и /mystatsall).

    Отображает статистику в виде эмбеда и позволяет листать страницы.
    """
    def __init__(self, title: str, games_data: List[Tuple[str, int]], user: Optional[discord.Member] = None, items_per_page: int = 5):
        """
        Инициализирует представление статистики пользователя.

        Args:
            title: Заголовок для эмбеда.
            games_data: Отсортированный список кортежей [(game_name, seconds)].
            user: Объект пользователя Discord (для аватарки).
            items_per_page: Количество игр на одной странице эмбеда.
        """
        super().__init__(timeout=86400) # 24 часа таймаут
        self.title = title
        self.games_data = games_data # Список [(game, seconds)]
        self.user = user
        self.items_per_page = items_per_page
        self.current_page = 0
        self.max_pages = max(1, (len(self.games_data) + self.items_per_page - 1) // self.items_per_page)
        self.message: Optional[discord.Message] = None # Для редактирования при таймауте

        # Обновляем состояние кнопок при инициализации
        self._update_buttons()

    def _update_buttons(self):
        """Обновляет состояние кнопок навигации."""
        for item in self.children:
            if not isinstance(item, ui.Button):
                continue
            if item.custom_id == "prev_button_stats":
                item.disabled = self.current_page == 0
            elif item.custom_id == "next_button_stats":
                item.disabled = self.current_page >= self.max_pages - 1

    def get_current_embed(self) -> discord.Embed:
        """
        Формирует эмбед для текущей страницы статистики.

        Returns:
            Объект discord.Embed для отправки.
        """
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.blue(),
            timestamp=datetime.now() # Время генерации эмбеда
        )
        if self.user:
            embed.set_thumbnail(url=self.user.display_avatar.url)

        # Получаем срез данных для текущей страницы
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.games_data))
        current_games = self.games_data[start_idx:end_idx]

        # Формируем описание эмбеда (список игр)
        description = ""
        if not current_games:
            description = "*Нет данных для отображения на этой странице.*"
        else:
            for i, (game_name, time_spent) in enumerate(current_games, start=start_idx + 1):
                formatted_time = format_time_short(time_spent) # Используем хелпер
                description += f"{i}. {game_name} - {formatted_time}\n"

        embed.description = description

        # Добавляем общее время
        total_time = sum(game[1] for game in self.games_data)
        embed.add_field(
            name="📊 Общее игровое время",
            value=f"{format_time_short(total_time)}", # Используем хелпер
            inline=False
        )

        # Устанавливаем футер с информацией о страницах
        if self.max_pages > 1:
            footer_text = f"Всего игр: {len(self.games_data)} • Страница {self.current_page + 1}/{self.max_pages}"
        else:
            footer_text = f"Всего игр: {len(self.games_data)}"
        embed.set_footer(text=footer_text)

        return embed

    # --- Кнопки ---

    @ui.button(label="⬅️ Назад", style=ButtonStyle.gray, custom_id="prev_button_stats")
    async def previous_button(self, interaction: Interaction, button: ui.Button):
        """Переключает на предыдущую страницу эмбеда."""
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        else:
            await interaction.response.defer()

    @ui.button(label="Вперед ➡️", style=ButtonStyle.gray, custom_id="next_button_stats")
    async def next_button(self, interaction: Interaction, button: ui.Button):
        """Переключает на следующую страницу эмбеда."""
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        else:
            await interaction.response.defer()

    async def on_timeout(self):
        """Отключает кнопки при истечении времени ожидания."""
        for item in self.children:
            if isinstance(item, (ui.Button, ui.Select)):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass # Игнорируем ошибки, если сообщение недоступно
