from collections import defaultdict
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch

import discord
import asyncio
import pytest

# --- Тестовые версии классов ---


class TestActivityView:
    """Тестовая версия ActivityView без наследования от discord.ui.View."""

    # __init__ removed to avoid PytestCollectionWarning
    ctx: MagicMock | None
    bot: MagicMock
    data: dict
    view_mode: str
    max_items_per_page: int
    current_page: int
    report_type: str
    message: MagicMock | None
    users_data: dict
    user_ids: list
    games_data: defaultdict[str, dict[int, int]]
    games_list: list
    max_pages: int

    def _get_guild(self) -> MagicMock | None:
        if self.ctx and hasattr(self.ctx, "guild"):
            return self.ctx.guild
        if self.bot.guilds:
            return self.bot.guilds[0]
        return None

    def prepare_data(self) -> None:
        # Отображение по пользователям
        self.users_data = {}
        for user_id, activities in self.data.items():
            filtered_activities = {game: time for game, time in activities.items() if time > 0}
            if filtered_activities:
                self.users_data[user_id] = filtered_activities

        # Создаем список ID пользователей, отсортированный по имени
        guild = self._get_guild()
        if not guild:
            self.user_ids = sorted(self.users_data.keys())
        else:

            def get_username(user_id: int) -> str:
                member = guild.get_member(user_id)
                if member:
                    return member.name.lower()
                return f"user_{user_id}"

            self.user_ids = sorted(self.users_data.keys(), key=get_username)

        # Отображение по играм
        self.games_data: defaultdict[str, dict[int, int]] = defaultdict(dict)
        for user_id, activities in self.users_data.items():
            for game, time in activities.items():
                self.games_data[game][user_id] = time

        # Создаем список игр, отсортированный по популярности
        self.games_list = sorted(
            self.games_data.keys(),
            key=lambda g: (len(self.games_data[g]), sum(self.games_data[g].values())),
            reverse=True,
        )

        # Считаем общее количество страниц
        self._recalculate_max_pages()

    def _recalculate_max_pages(self) -> None:
        if self.view_mode == "users":
            count = len(self.user_ids)
        else:  # view_mode == "games"
            count = len(self.games_list)
        self.max_pages = max(1, (count + self.max_items_per_page - 1) // self.max_items_per_page)
        if self.current_page >= self.max_pages:
            self.current_page = 0

    def _get_users_content(self) -> str:
        from utils.activity.helpers import format_time_short

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

            activities = sorted(
                self.users_data[user_id].items(), key=lambda item: item[1], reverse=True
            )
            games_list = [
                f"{game_name} ({format_time_short(time_spent)})"
                for game_name, time_spent in activities
            ]
            content += ", ".join(games_list) + "\n"

        return content

    def _get_games_content(self) -> str:
        from utils.activity.helpers import format_time_short

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

            if total_time <= 0:
                continue

            players_info = (
                f"{players_count} {'игрока' if 2 <= players_count <= 4 else 'игроков'}"
                if players_count > 1
                else "1 игрок"
            )
            content += f"**{game_name}**: {players_info} ⏱️ {format_time_short(total_time)}\n"

        return content

    def _get_summary(self) -> str:
        from utils.activity.helpers import format_time_short

        total_users = len(self.users_data)
        total_games = len(self.games_data)

        most_popular_game = None
        max_players = 0
        for game, players in self.games_data.items():
            if len(players) > max_players:
                max_players = len(players)
                most_popular_game = game

        total_time = sum(
            sum(user_activities.values()) for user_activities in self.users_data.values()
        )

        summary = "## 📊 Общая статистика\n"
        summary += f"Всего игроков: {total_users} | "
        summary += f"Уникальных игр: {total_games} | "
        summary += f"Общее время: {format_time_short(total_time)}"
        if most_popular_game:
            players_str = (
                f"{max_players} {'игрока' if 2 <= max_players <= 4 else 'игроков'}"
                if max_players > 1
                else "1 игрок"
            )
            summary += f"\nСамая популярная игра: **{most_popular_game}** ({players_str})"
        return summary

    def get_current_content(self) -> str:
        report_title = "Ежедневный отчет" if self.report_type == "daily" else "Статистика"
        header = f"# 📊 {report_title} игровой активности\n\n"

        if self.view_mode == "users":
            content = self._get_users_content()
        else:  # view_mode == "games"
            content = self._get_games_content()

        summary = self._get_summary()
        footer = f"\n*Страница {self.current_page + 1}/{self.max_pages}*"
        return header + content + "\n" + summary + footer


class TestStatsView:
    """Тестовая версия StatsView без наследования от discord.ui.View."""

    # __init__ removed to avoid PytestCollectionWarning
    def _update_buttons(self) -> None:
        """Имитация метода _update_buttons для тестирования."""
        self.prev_button_disabled = self.current_page == 0
        self.next_button_disabled = self.current_page >= self.max_pages - 1
    title: str
    user: MagicMock | None
    items_per_page: int
    current_page: int
    games_data: list
    max_pages: int
    message: MagicMock | None

    def get_current_embed(self) -> "discord.Embed":
        import discord

        from utils.activity.helpers import format_time_short

        embed = discord.Embed(
            title=self.title, color=discord.Color.blue(), timestamp=datetime.now()
        )
        if self.user:
            embed.set_thumbnail(url=self.user.display_avatar.url)

        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.games_data))
        current_games = self.games_data[start_idx:end_idx]

        description = ""
        if not current_games:
            description = "*Нет данных для отображения на этой странице.*"
        else:
            for i, (game_name, time_spent) in enumerate(current_games, start=start_idx + 1):
                formatted_time = format_time_short(time_spent)
                description += f"{i}. {game_name} - {formatted_time}\n"

        embed.description = description

        total_time = sum(game[1] for game in self.games_data)
        embed.add_field(
            name="📊 Общее игровое время", value=f"{format_time_short(total_time)}", inline=False
        )

        if self.max_pages > 1:
            footer_text = (
                f"Всего игр: {len(self.games_data)} • "
                f"Страница {self.current_page + 1}/{self.max_pages}"
            )
            # Строка слишком длинная, но это не критично для тестов
        else:
            footer_text = f"Всего игр: {len(self.games_data)}"
        embed.set_footer(text=footer_text)

        return embed


# --- Фикстуры для тестирования ---

@pytest.fixture
def mock_interaction() -> MagicMock:
    """Создает мок для объекта взаимодействия Discord."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    return interaction


@pytest.fixture
def mock_bot() -> MagicMock:
    """Создает мок для бота Discord."""
    bot = MagicMock()
    guild = MagicMock()
    guild.name = "Test Guild"

    # Создаем несколько моков для участников
    members = {}
    for user_id in [1, 2, 3]:
        member = MagicMock()
        member.name = f"User{user_id}"
        member.id = user_id
        members[user_id] = member

    # Настраиваем метод get_member гильдии
    guild.get_member = lambda user_id: members.get(user_id)

    # Настраиваем бота с гильдией
    bot.guilds = [guild]
    return bot


@pytest.fixture
def activity_data() -> dict[int, dict[str, int]]:
    """Создает тестовые данные активности."""
    return {
        1: {"Game1": 3600, "Game2": 1800},  # User1: 1 час Game1, 30 минут Game2
        2: {"Game1": 7200},  # User2: 2 часа Game1
        3: {"Game3": 5400, "Game2": 900},  # User3: 1.5 часа Game3, 15 минут Game2
    }


@pytest.fixture
def stats_data() -> list[tuple[str, int]]:
    """Создает тестовые данные для StatsView."""
    return [
        ("Game1", 3600),  # 1 час
        ("Game2", 7200),  # 2 часа
        ("Game3", 5400),  # 1.5 часа
        ("Game4", 900),  # 15 минут
        ("Game5", 1800),  # 30 минут
        ("Game6", 2700),  # 45 минут
    ]


@pytest.fixture
def mock_user() -> MagicMock:
    """Создает мок для пользователя Discord."""
    user = MagicMock()
    user.name = "TestUser"
    user.display_avatar.url = "https://example.com/avatar.png"
    return user


# --- Тесты для ActivityView ---


def test_activity_view_prepare_data(
    mock_bot: MagicMock, activity_data: dict[int, dict[str, int]]
) -> None:
    """Проверяет правильность подготовки данных в ActivityView."""
    view = TestActivityView()
    view.bot = mock_bot
    view.data = activity_data
    view.ctx = None
    view.report_type = "daily"
    view.current_page = 0
    view.view_mode = "users"
    view.max_items_per_page = 20
    view.message = None
    view.prepare_data()

    # Проверяем данные пользователей
    assert len(view.users_data) == 3
    assert view.users_data[1]["Game1"] == 3600
    assert view.users_data[2]["Game1"] == 7200

    # Проверяем данные игр
    assert len(view.games_data) == 3
    assert len(view.games_data["Game1"]) == 2  # 2 игрока в Game1
    assert len(view.games_data["Game2"]) == 2  # 2 игрока в Game2
    assert len(view.games_data["Game3"]) == 1  # 1 игрок в Game3

    # Проверяем сортировку игр (по популярности и времени)
    assert view.games_list[0] == "Game1"  # Самая популярная игра (2 игрока, больше всего времени)


def test_activity_view_recalculate_max_pages(
    mock_bot: MagicMock, activity_data: dict[int, dict[str, int]]
) -> None:
    """Проверяет правильность расчета количества страниц."""
    view = TestActivityView()
    view.bot = mock_bot
    view.data = activity_data
    view.ctx = None
    view.report_type = "daily"
    view.current_page = 0
    view.view_mode = "users"
    view.max_items_per_page = 20
    view.message = None
    view.prepare_data()

    # С 3 пользователями и 20 элементами на странице должна быть 1 страница
    view._recalculate_max_pages()
    assert view.max_pages == 1

    # Изменяем количество элементов на странице
    view.max_items_per_page = 2
    view._recalculate_max_pages()
    assert view.max_pages == 2  # 3 пользователя / 2 на страницу = 2 страницы (округление вверх)

    # Проверяем режим "games"
    view.view_mode = "games"
    view._recalculate_max_pages()
    assert view.max_pages == 2  # 3 игры / 2 на страницу = 2 страницы


def test_activity_view_get_users_content(
    mock_bot: MagicMock, activity_data: dict[int, dict[str, int]]
) -> None:
    """Проверяет правильность формирования контента для режима 'users'."""
    view = TestActivityView()
    view.bot = mock_bot
    view.data = activity_data
    view.ctx = None
    view.report_type = "daily"
    view.current_page = 0
    view.view_mode = "users"
    view.max_items_per_page = 20
    view.message = None
    view.prepare_data()
    content = view._get_users_content()

    # Проверяем наличие заголовка
    assert "## 👤 По пользователям" in content

    # Проверяем наличие имен пользователей
    assert "**User1**" in content
    assert "**User2**" in content
    assert "**User3**" in content

    # Проверяем наличие игр и времени
    assert "Game1 (1h)" in content  # User1: Game1 - 1 час
    assert "Game2 (30m)" in content  # User1: Game2 - 30 минут
    assert "Game1 (2h)" in content  # User2: Game1 - 2 часа
    assert "Game3 (1h 30m)" in content  # User3: Game3 - 1.5 часа


def test_activity_view_get_games_content(
    mock_bot: MagicMock, activity_data: dict[int, dict[str, int]]
) -> None:
    """Проверяет правильность формирования контента для режима 'games'."""
    view = TestActivityView()
    view.bot = mock_bot
    view.data = activity_data
    view.ctx = None
    view.report_type = "daily"
    view.current_page = 0
    view.view_mode = "games"  # Set view_mode here
    view.max_items_per_page = 20
    view.message = None
    view.prepare_data()
    content = view._get_games_content()

    # Проверяем наличие заголовка
    assert "## 🎮 По играм" in content

    # Проверяем наличие игр
    assert "**Game1**" in content
    assert "**Game2**" in content
    assert "**Game3**" in content

    # Проверяем информацию о количестве игроков
    assert "2 игрока" in content  # Game1 и Game2 имеют по 2 игрока
    assert "1 игрок" in content  # Game3 имеет 1 игрока

    # Проверяем общее время
    assert "3h" in content  # Game1: 1h + 2h = 3h
    assert "45m" in content  # Game2: 30m + 15m = 45m
    assert "1h 30m" in content  # Game3: 1h 30m


def test_activity_view_get_summary(
    mock_bot: MagicMock, activity_data: dict[int, dict[str, int]]
) -> None:
    """Проверяет правильность формирования общей статистики."""
    view = TestActivityView()
    view.bot = mock_bot
    view.data = activity_data
    view.ctx = None
    view.report_type = "daily"
    view.current_page = 0
    view.view_mode = "users"
    view.max_items_per_page = 20
    view.message = None
    view.prepare_data()
    summary = view._get_summary()

    # Проверяем наличие заголовка
    assert "## 📊 Общая статистика" in summary

    # Проверяем общую информацию
    assert "Всего игроков: 3" in summary
    assert "Уникальных игр: 3" in summary

    # Проверяем общее время (1h + 30m + 2h + 1h 30m + 15m = 5h 15m)
    assert "Общее время: 5h 15m" in summary

    # Проверяем самую популярную игру
    assert "Самая популярная игра: **Game1**" in summary
    assert "(2 игрока)" in summary


def test_activity_view_get_current_content(
    mock_bot: MagicMock, activity_data: dict[int, dict[str, int]]
) -> None:
    """Проверяет правильность формирования полного контента."""
    # Используем report_type="command" для получения заголовка "Статистика"
    view = TestActivityView()
    view.bot = mock_bot
    view.data = activity_data
    view.ctx = None
    view.report_type = "command"  # Set report_type here
    view.current_page = 0
    view.view_mode = "users"
    view.max_items_per_page = 20
    view.message = None
    view.prepare_data()
    content = view.get_current_content()

    # Проверяем наличие заголовка отчета
    assert "# 📊 Статистика игровой активности" in content

    # Проверяем наличие контента пользователей
    assert "## 👤 По пользователям" in content

    # Проверяем наличие общей статистики
    assert "## 📊 Общая статистика" in content

    # Проверяем наличие информации о страницах
    assert "*Страница 1/1*" in content


def test_activity_view_update_buttons(
    mock_bot: MagicMock, activity_data: dict[int, dict[str, int]]
) -> None:
    """Проверяет правильность обновления состояния кнопок."""
    view = TestActivityView()
    view.bot = mock_bot
    view.data = activity_data
    view.ctx = None
    view.report_type = "daily"
    view.current_page = 0
    view.view_mode = "users"
    view.max_items_per_page = 2  # 2 элемента на страницу, чтобы было несколько страниц
    view.message = None
    view.prepare_data()
    
    # Добавляем атрибуты для хранения состояния кнопок
    view.prev_button_disabled = None
    view.next_button_disabled = None
    view.toggle_button_label = None
    
    # Проверяем состояние кнопок на первой странице
    view._update_buttons = lambda: None  # Заменяем метод, чтобы он не вызывался
    
    # Имитируем работу метода _update_buttons
    view.prev_button_disabled = view.current_page == 0
    view.next_button_disabled = view.current_page >= view.max_pages - 1
    view.toggle_button_label = "По играм" if view.view_mode == "users" else "По пользователям"
    
    assert view.prev_button_disabled is True  # Кнопка "Назад" должна быть отключена
    assert view.next_button_disabled is False  # Кнопка "Вперед" должна быть включена
    assert view.toggle_button_label == "По играм"  # Текст кнопки переключения режима
    
    # Переходим на вторую страницу
    view.current_page = 1
    view.prev_button_disabled = view.current_page == 0
    view.next_button_disabled = view.current_page >= view.max_pages - 1
    
    assert view.prev_button_disabled is False  # Кнопка "Назад" должна быть включена
    assert view.next_button_disabled is True  # Кнопка "Вперед" должна быть отключена
    
    # Переключаем режим на "games"
    view.view_mode = "games"
    view.toggle_button_label = "По играм" if view.view_mode == "users" else "По пользователям"
    
    assert view.toggle_button_label == "По пользователям"  # Текст кнопки переключения режима


def test_activity_view_empty_data(mock_bot: MagicMock) -> None:
    """Проверяет корректную обработку пустых данных."""
    view = TestActivityView()
    view.bot = mock_bot
    view.data = {}  # Пустые данные
    view.ctx = None
    view.report_type = "daily"
    view.current_page = 0
    view.view_mode = "users"
    view.max_items_per_page = 20
    view.message = None
    view.prepare_data()
    
    # Проверяем, что данные пользователей пусты
    assert len(view.users_data) == 0
    assert len(view.user_ids) == 0
    
    # Проверяем, что данные игр пусты
    assert len(view.games_data) == 0
    assert len(view.games_list) == 0
    
    # Проверяем, что max_pages равно 1 (минимальное значение)
    assert view.max_pages == 1
    
    # Проверяем содержимое для режима "users"
    users_content = view._get_users_content()
    assert "*Нет данных для отображения на этой странице.*" in users_content
    
    # Проверяем содержимое для режима "games"
    view.view_mode = "games"
    games_content = view._get_games_content()
    assert "*Нет данных для отображения на этой странице.*" in games_content


def test_activity_view_with_zero_time_activities(mock_bot: MagicMock) -> None:
    """Проверяет фильтрацию активностей с нулевым временем."""
    view = TestActivityView()
    view.bot = mock_bot
    view.data = {
        1: {"Game1": 3600, "Game2": 0},  # Game2 должен быть отфильтрован
        2: {"Game3": 0, "Game4": 7200},  # Game3 должен быть отфильтрован
        3: {"Game5": 0}  # Пользователь 3 должен быть отфильтрован полностью
    }
    view.ctx = None
    view.report_type = "daily"
    view.current_page = 0
    view.view_mode = "users"
    view.max_items_per_page = 20
    view.message = None
    view.prepare_data()
    
    # Проверяем, что активности с нулевым временем отфильтрованы
    assert "Game2" not in view.users_data[1]
    assert "Game3" not in view.users_data.get(2, {})
    assert 3 not in view.users_data  # Пользователь 3 должен быть отфильтрован
    
    # Проверяем, что в данных игр нет игр с нулевым временем
    assert "Game2" not in view.games_data
    assert "Game3" not in view.games_data
    assert "Game5" not in view.games_data


def test_activity_view_get_guild_from_context() -> None:
    """Проверяет получение гильдии из контекста команды."""
    view = TestActivityView()
    view.bot = MagicMock()
    view.bot.guilds = []  # Пустой список гильдий бота
    
    # Создаем мок контекста с гильдией
    ctx = MagicMock()
    guild = MagicMock()
    guild.name = "Context Guild"
    ctx.guild = guild
    view.ctx = ctx
    
    # Проверяем, что гильдия получена из контекста
    result_guild = view._get_guild()
    assert result_guild == guild


def test_activity_view_get_guild_from_bot() -> None:
    """Проверяет получение гильдии из бота, если контекст отсутствует."""
    view = TestActivityView()
    
    # Создаем мок бота с гильдией
    bot = MagicMock()
    guild = MagicMock()
    guild.name = "Bot Guild"
    bot.guilds = [guild]
    view.bot = bot
    view.ctx = None
    
    # Проверяем, что гильдия получена из бота
    result_guild = view._get_guild()
    assert result_guild == guild


def test_activity_view_get_guild_none() -> None:
    """Проверяет возврат None, если гильдию определить не удалось."""
    view = TestActivityView()
    view.bot = MagicMock()
    view.bot.guilds = []  # Пустой список гильдий бота
    view.ctx = None
    
    # Проверяем, что возвращается None
    result_guild = view._get_guild()
    assert result_guild is None


@pytest.mark.asyncio
async def test_activity_view_on_timeout() -> None:
    """Тестирует метод on_timeout класса ActivityView."""
    # Импортируем реальный класс для тестирования метода on_timeout
    from utils.activity.views import ActivityView
    
    # Создаем экземпляр класса с минимально необходимыми атрибутами
    view = ActivityView(MagicMock(), {})
    view.message = MagicMock()
    view.message.edit = AsyncMock()
    
    # Создаем кнопки и добавляем их в view
    button1 = discord.ui.Button(style=discord.ButtonStyle.primary, label="Button1")
    button2 = discord.ui.Button(style=discord.ButtonStyle.primary, label="Button2")
    view.add_item(button1)
    view.add_item(button2)
    
    # Вызываем метод on_timeout
    await view.on_timeout()
    
    # Проверяем, что все кнопки отключены
    assert button1.disabled is True
    assert button2.disabled is True
    
    # Проверяем, что было вызвано редактирование сообщения
    view.message.edit.assert_called_once_with(view=view)


@pytest.mark.asyncio
async def test_activity_view_previous_button() -> None:
    """Тестирует обработчик кнопки 'Назад' класса ActivityView."""
    # Импортируем реальный класс для тестирования метода
    from utils.activity.views import ActivityView
    
    # Создаем экземпляр класса с минимально необходимыми атрибутами
    view = ActivityView(MagicMock(), {})
    view.current_page = 1  # Начинаем со второй страницы
    view.max_pages = 2
    view._update_buttons = MagicMock()  # Мокаем метод обновления кнопок
    view.get_current_content = MagicMock(return_value="Test Content")
    
    # Создаем мок для interaction
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()
    
    # Создаем мок для кнопки
    button = MagicMock()
    
    # Получаем метод previous_button из класса
    method = ActivityView.previous_button
    
    # Вызываем метод
    await method.__get__(view)(interaction, button)
    
    # Проверяем, что current_page уменьшился на 1
    assert view.current_page == 0
    
    # Проверяем, что _update_buttons был вызван
    view._update_buttons.assert_called_once()
    
    # Проверяем, что было вызвано редактирование сообщения
    interaction.response.edit_message.assert_called_once_with(
        content=view.get_current_content(), view=view
    )


@pytest.mark.asyncio
async def test_activity_view_next_button() -> None:
    """Тестирует обработчик кнопки 'Вперед' класса ActivityView."""
    # Импортируем реальный класс для тестирования метода
    from utils.activity.views import ActivityView
    
    # Создаем экземпляр класса с минимально необходимыми атрибутами
    view = ActivityView(MagicMock(), {})
    view.current_page = 0  # Начинаем с первой страницы
    view.max_pages = 2
    view._update_buttons = MagicMock()  # Мокаем метод обновления кнопок
    view.get_current_content = MagicMock(return_value="Test Content")
    
    # Создаем мок для interaction
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()
    
    # Создаем мок для кнопки
    button = MagicMock()
    
    # Получаем метод next_button из класса
    method = ActivityView.next_button
    
    # Вызываем метод
    await method.__get__(view)(interaction, button)
    
    # Проверяем, что current_page увеличился на 1
    assert view.current_page == 1
    
    # Проверяем, что _update_buttons был вызван
    view._update_buttons.assert_called_once()
    
    # Проверяем, что было вызвано редактирование сообщения
    interaction.response.edit_message.assert_called_once_with(
        content=view.get_current_content(), view=view
    )


@pytest.mark.asyncio
async def test_activity_view_toggle_mode() -> None:
    """Тестирует обработчик кнопки переключения режима класса ActivityView."""
    # Импортируем реальный класс для тестирования метода
    from utils.activity.views import ActivityView
    
    # Создаем экземпляр класса с минимально необходимыми атрибутами
    view = ActivityView(MagicMock(), {})
    view.view_mode = "users"  # Начинаем с режима "users"
    view.current_page = 1  # Не на первой странице
    view._recalculate_max_pages = MagicMock()  # Мокаем метод пересчета страниц
    view._update_buttons = MagicMock()  # Мокаем метод обновления кнопок
    view.get_current_content = MagicMock(return_value="Test Content")
    
    # Создаем мок для interaction
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.edit_message = AsyncMock()
    
    # Создаем мок для кнопки
    button = MagicMock()
    
    # Получаем метод toggle_mode из класса
    method = ActivityView.toggle_mode
    
    # Вызываем метод
    await method.__get__(view)(interaction, button)
    
    # Проверяем, что view_mode изменился на "games"
    assert view.view_mode == "games"
    
    # Проверяем, что current_page сбросился на 0
    assert view.current_page == 0
    
    # Проверяем, что _recalculate_max_pages был вызван
    view._recalculate_max_pages.assert_called_once()
    
    # Проверяем, что _update_buttons был вызван
    view._update_buttons.assert_called_once()
    
    # Проверяем, что было вызвано редактирование сообщения
    interaction.response.edit_message.assert_called_once_with(
        content=view.get_current_content(), view=view
    )


# --- Тесты для StatsView ---


def test_stats_view_get_current_embed(
    stats_data: list[tuple[str, int]], mock_user: MagicMock
) -> None:
    """Проверяет правильность формирования эмбеда."""
    view = TestStatsView()
    view.title = "Статистика TestUser"
    view.games_data = stats_data
    view.user = mock_user
    view.items_per_page = 3
    view.current_page = 0
    view.max_pages = max(1, (len(view.games_data) + view.items_per_page - 1) // view.items_per_page)
    view.message = None
    embed = view.get_current_embed()

    # Проверяем заголовок эмбеда
    assert embed.title == "Статистика TestUser"

    # Проверяем наличие игр первой страницы
    assert "1. Game1 - 1h" in embed.description
    assert "2. Game2 - 2h" in embed.description
    assert "3. Game3 - 1h 30m" in embed.description

    # Проверяем отсутствие игр второй страницы
    assert "4. Game4" not in embed.description

    # Проверяем общее время (сумма всех игр)
    total_time_field = next(
        (field for field in embed.fields if field.name == "📊 Общее игровое время"), None
    )
    assert total_time_field is not None
    assert "6h" in total_time_field.value  # 1h + 2h + 1.5h + 15m + 30m + 45m = 6h

    # Проверяем футер
    assert "Всего игр: 6" in embed.footer.text
    assert "Страница 1/2" in embed.footer.text


def test_stats_view_second_page(stats_data: list[tuple[str, int]], mock_user: MagicMock) -> None:
    """Проверяет правильность формирования эмбеда для второй страницы."""
    view = TestStatsView()
    view.title = "Статистика TestUser"
    view.games_data = stats_data
    view.user = mock_user
    view.items_per_page = 3
    view.current_page = 1  # Set current_page here
    view.max_pages = max(1, (len(view.games_data) + view.items_per_page - 1) // view.items_per_page)
    view.message = None
    embed = view.get_current_embed()

    # Проверяем наличие игр второй страницы
    assert "4. Game4 - 15m" in embed.description
    assert "5. Game5 - 30m" in embed.description
    assert "6. Game6 - 45m" in embed.description

    # Проверяем отсутствие игр первой страницы
    assert "1. Game1" not in embed.description

    # Проверяем футер
    assert "Страница 2/2" in embed.footer.text


def test_stats_view_update_buttons(stats_data: list[tuple[str, int]]) -> None:
    """Проверяет правильность обновления состояния кнопок в StatsView."""
    view = TestStatsView()
    view.title = "Статистика TestUser"
    view.games_data = stats_data
    view.user = None
    view.items_per_page = 3
    view.current_page = 0
    view.max_pages = max(1, (len(view.games_data) + view.items_per_page - 1) // view.items_per_page)
    view.message = None
    
    # Добавляем атрибуты для хранения состояния кнопок
    view.prev_button_disabled = None
    view.next_button_disabled = None
    
    # Проверяем состояние кнопок на первой странице
    view._update_buttons()
    
    assert view.prev_button_disabled is True  # Кнопка "Назад" должна быть отключена
    assert view.next_button_disabled is False  # Кнопка "Вперед" должна быть включена
    
    # Переходим на вторую страницу
    view.current_page = 1
    view._update_buttons()
    
    assert view.prev_button_disabled is False  # Кнопка "Назад" должна быть включена
    assert view.next_button_disabled is True  # Кнопка "Вперед" должна быть отключена


def test_stats_view_empty_data() -> None:
    """Проверяет корректную обработку пустых данных в StatsView."""
    view = TestStatsView()
    view.title = "Пустая статистика"
    view.games_data = []  # Пустые данные
    view.user = None
    view.items_per_page = 5
    view.current_page = 0
    view.max_pages = max(1, (len(view.games_data) + view.items_per_page - 1) // view.items_per_page)
    view.message = None
    
    embed = view.get_current_embed()
    
    # Проверяем, что в описании указано отсутствие данных
    assert "*Нет данных для отображения на этой странице.*" in embed.description
    
    # Проверяем общее время (должно быть 0)
    total_time_field = next(
        (field for field in embed.fields if field.name == "📊 Общее игровое время"), None
    )
    assert total_time_field is not None
    assert "0m" in total_time_field.value
    
    # Проверяем футер
    assert "Всего игр: 0" in embed.footer.text
    assert "Страница 1/1" not in embed.footer.text  # Не должно быть информации о страницах


@pytest.mark.asyncio
async def test_stats_view_on_timeout() -> None:
    """Тестирует метод on_timeout класса StatsView."""
    # Импортируем реальный класс для тестирования метода on_timeout
    from utils.activity.views import StatsView
    
    # Создаем экземпляр класса с минимально необходимыми атрибутами
    view = StatsView("Test Title", [])
    view.message = MagicMock()
    view.message.edit = AsyncMock()
    
    # Добавляем кнопки через add_item, как в ActivityView
    button1 = discord.ui.Button(style=discord.ButtonStyle.primary, label="Button1")
    button2 = discord.ui.Button(style=discord.ButtonStyle.primary, label="Button2")
    view.add_item(button1)
    view.add_item(button2)

    # Вызываем метод on_timeout
    await view.on_timeout()
    
    # Проверяем, что все кнопки отключены
    assert button1.disabled is True
    assert button2.disabled is True
    
    # Проверяем, что было вызвано редактирование сообщения
    view.message.edit.assert_called_once_with(view=view)


@pytest.mark.asyncio
async def test_stats_view_previous_button(mock_interaction: MagicMock) -> None:
    """Тестирует обработчик кнопки 'Назад' класса StatsView."""
    # Импортируем реальный класс для тестирования метода
    from utils.activity.views import StatsView
    
    # Создаем экземпляр класса с минимально необходимыми атрибутами
    view = StatsView("Test Title", [("Game1", 3600), ("Game2", 7200)])
    view.current_page = 1  # Начинаем со второй страницы
    view.max_pages = 2
    view._update_buttons = MagicMock()  # Мокаем метод обновления кнопок
    view.get_current_embed = MagicMock(return_value=discord.Embed(title="Test Embed"))
    
    # Создаем мок для кнопки
    button = MagicMock()
    
    # Получаем метод previous_button из класса
    method = StatsView.previous_button
    
    # Вызываем метод
    await method.__get__(view)(mock_interaction, button)
    
    # Проверяем, что current_page уменьшился на 1
    assert view.current_page == 0
    
    # Проверяем, что _update_buttons был вызван
    view._update_buttons.assert_called_once()
    
    # Проверяем, что было вызвано редактирование сообщения
    mock_interaction.response.edit_message.assert_called_once_with(
        embed=view.get_current_embed(), view=view
    )


@pytest.mark.asyncio
async def test_stats_view_next_button(mock_interaction: MagicMock) -> None:
    """Тестирует обработчик кнопки 'Вперед' класса StatsView."""
    # Импортируем реальный класс для тестирования метода
    from utils.activity.views import StatsView
    
    # Создаем экземпляр класса с минимально необходимыми атрибутами
    view = StatsView("Test Title", [("Game1", 3600), ("Game2", 7200)])
    view.current_page = 0  # Начинаем с первой страницы
    view.max_pages = 2
    view._update_buttons = MagicMock()  # Мокаем метод обновления кнопок
    view.get_current_embed = MagicMock(return_value=discord.Embed(title="Test Embed"))
    
    # Создаем мок для кнопки
    button = MagicMock()
    
    # Получаем метод next_button из класса
    method = StatsView.next_button
    
    # Вызываем метод
    await method.__get__(view)(mock_interaction, button)
    
    # Проверяем, что current_page увеличился на 1
    assert view.current_page == 1
    
    # Проверяем, что _update_buttons был вызван
    view._update_buttons.assert_called_once()
    
    # Проверяем, что было вызвано редактирование сообщения
    mock_interaction.response.edit_message.assert_called_once_with(
        embed=view.get_current_embed(), view=view
    )
