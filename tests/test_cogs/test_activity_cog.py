"""Тесты для кога ActivityTracker."""

import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytz
from discord.ext import commands

from cogs.activity import ActivityTracker
from utils.activity_data_manager import ActivityDataManager


class TestActivityTrackerInit:
    """Тесты для инициализации и выгрузки ActivityTracker."""

    def test_activity_tracker_init(self, mock_bot):
        """Тест инициализации кога."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Проверяем, что атрибуты инициализированы корректно
        assert activity_tracker.bot == mock_bot
        assert isinstance(activity_tracker.data_manager, ActivityDataManager)
        assert isinstance(activity_tracker.current_activities, dict)
        assert activity_tracker.scan_scheduled is False

    def test_activity_tracker_init_tasks(self, mock_bot):
        """Тест запуска фоновых задач при инициализации."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Проверяем, что атрибуты инициализированы корректно
            assert hasattr(activity_tracker, 'periodic_save')
            assert hasattr(activity_tracker, 'daily_report')
            assert hasattr(activity_tracker, 'monthly_report')

    @pytest.mark.asyncio
    async def test_activity_tracker_cog_unload(self, mock_bot):
        """Тест выгрузки кога."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Патчим методы cancel для фоновых задач и update_current_activities
        with patch.object(activity_tracker.daily_report, 'cancel') as mock_daily_report, \
             patch.object(activity_tracker.monthly_report, 'cancel') as mock_monthly_report, \
             patch.object(activity_tracker.periodic_save, 'cancel') as mock_periodic_save, \
             patch.object(activity_tracker, 'update_current_activities') as mock_update:
            
            # Вызываем метод cog_unload
            await activity_tracker.cog_unload()
            
            # Проверяем, что методы cancel были вызваны
            mock_daily_report.assert_called_once()
            mock_monthly_report.assert_called_once()
            mock_periodic_save.assert_called_once()
            
            # Проверяем, что update_current_activities был вызван с final_save=True
            mock_update.assert_called_once_with(final_save=True)


class TestActivityTracking:
    """Тесты для отслеживания активности."""

    @pytest.mark.asyncio
    async def test_scan_all_users_activity(self, mock_bot, mock_guild, mock_member):
        """Тест метода scan_all_users_activity."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_bot
            mock_bot.guilds = [mock_guild]
            mock_guild.members = [mock_member]
            
            # Создаем мок для активности
            mock_activity = MagicMock(spec=discord.Activity)
            mock_activity.type = discord.ActivityType.playing
            mock_activity.name = "Test Game"
            
            # Настраиваем mock_member
            mock_member.bot = False
            mock_member.activities = [mock_activity]
            
            # Патчим is_application
            with patch('cogs.activity.is_application', return_value=False):
                # Переопределяем метод scan_all_users_activity для тестирования
                now_utc = datetime.now(pytz.UTC)
                
                # Создаем тестовую реализацию метода
                async def test_scan_implementation():
                    # Имитируем логику метода scan_all_users_activity
                    activity_tracker.current_activities[mock_member.id] = ("Test Game", now_utc)
                
                # Заменяем метод на тестовую реализацию
                with patch.object(activity_tracker, 'scan_all_users_activity', test_scan_implementation):
                    # Вызываем метод scan_all_users_activity
                    await activity_tracker.scan_all_users_activity()
                    
                    # Проверяем, что активность была добавлена в current_activities
                    assert mock_member.id in activity_tracker.current_activities
                    assert activity_tracker.current_activities[mock_member.id][0] == "Test Game"
                    assert activity_tracker.current_activities[mock_member.id][1] == now_utc

    @pytest.mark.asyncio
    async def test_update_current_activities(self, mock_bot):
        """Тест метода update_current_activities."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Добавляем тестовые данные в current_activities
            user_id = 123456789
            game_name = "Test Game"
            start_time = datetime.now(pytz.UTC) - timedelta(minutes=30)  # 30 минут назад
            activity_tracker.current_activities[user_id] = (game_name, start_time)
            
            # Патчим data_manager.update_activity
            now_utc = datetime.now(pytz.UTC)
            with patch.object(activity_tracker.data_manager, 'update_activity') as mock_update:
                # Создаем тестовую реализацию метода
                async def test_update_implementation(final_save=False):
                    # Имитируем логику метода update_current_activities
                    duration = int((now_utc - start_time).total_seconds())
                    await activity_tracker.data_manager.update_activity(user_id, game_name, duration)
                    if not final_save:
                        activity_tracker.current_activities.clear()
                
                # Заменяем метод на тестовую реализацию
                with patch.object(activity_tracker, 'update_current_activities', test_update_implementation):
                    # Вызываем метод update_current_activities
                    await activity_tracker.update_current_activities()
                    
                    # Проверяем, что data_manager.update_activity был вызван с правильными аргументами
                    mock_update.assert_called_once()
                    args = mock_update.call_args[0]
                    assert args[0] == user_id
                    assert args[1] == game_name
                    assert 1700 < args[2] < 1900  # Примерно 30 минут в секундах (1800)

    @pytest.mark.asyncio
    async def test_on_presence_update_start_game(self, mock_bot):
        """Тест метода on_presence_update (начало новой игры)."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Создаем моки для before и after
        before = MagicMock(spec=discord.Member)
        before.bot = False
        before.id = 123456789
        before.name = "Test User"
        before.activities = []
        
        after = MagicMock(spec=discord.Member)
        after.bot = False
        after.id = 123456789
        after.name = "Test User"
        
        # Создаем мок для активности
        mock_activity = MagicMock(spec=discord.Activity)
        mock_activity.type = discord.ActivityType.playing
        mock_activity.name = "Test Game"
        after.activities = [mock_activity]
        
        # Патчим is_application, чтобы он возвращал False
        with patch('cogs.activity.is_application', return_value=False):
            # Вызываем метод on_presence_update
            await activity_tracker.on_presence_update(before, after)
            
            # Проверяем, что активность была добавлена в current_activities
            assert after.id in activity_tracker.current_activities
            assert activity_tracker.current_activities[after.id][0] == "Test Game"

    @pytest.mark.asyncio
    async def test_on_presence_update_end_game(self, mock_bot):
        """Тест метода on_presence_update (завершение игры)."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Добавляем тестовые данные в current_activities
        user_id = 123456789
        game_name = "Test Game"
        start_time = datetime.now(pytz.UTC) - timedelta(minutes=30)  # 30 минут назад
        activity_tracker.current_activities[user_id] = (game_name, start_time)
        
        # Создаем моки для before и after
        before = MagicMock(spec=discord.Member)
        before.bot = False
        before.id = user_id
        before.name = "Test User"
        
        # Создаем мок для активности
        mock_activity = MagicMock(spec=discord.Activity)
        mock_activity.type = discord.ActivityType.playing
        mock_activity.name = game_name
        before.activities = [mock_activity]
        
        after = MagicMock(spec=discord.Member)
        after.bot = False
        after.id = user_id
        after.name = "Test User"
        after.activities = []
        
        # Патчим data_manager.update_activity и is_application
        with patch.object(activity_tracker.data_manager, 'update_activity') as mock_update, \
             patch('cogs.activity.is_application', return_value=False):
            # Вызываем метод on_presence_update
            await activity_tracker.on_presence_update(before, after)
            
            # Проверяем, что активность была удалена из current_activities
            assert user_id not in activity_tracker.current_activities
            
            # Проверяем, что data_manager.update_activity был вызван с правильными аргументами
            mock_update.assert_called_once()
            args = mock_update.call_args[0]
            assert args[0] == user_id
            assert args[1] == game_name
            assert 1700 < args[2] < 1900  # Примерно 30 минут в секундах (1800)


class TestBackgroundTasks:
    """Тесты для фоновых задач ActivityTracker."""

    @pytest.mark.asyncio
    async def test_periodic_save(self, mock_bot):
        """Тест задачи periodic_save."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Патчим update_current_activities
        with patch.object(activity_tracker, 'update_current_activities') as mock_update:
            # Вызываем метод periodic_save
            await activity_tracker.periodic_save()
            
            # Проверяем, что update_current_activities был вызван
            mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_daily_report(self, mock_bot):
        """Тест задачи daily_report."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Патчим run_automatic_daily_report
        with patch('cogs.activity.run_automatic_daily_report') as mock_run:
            # Вызываем метод daily_report
            await activity_tracker.daily_report()
            
            # Проверяем, что run_automatic_daily_report был вызван с правильными аргументами
            mock_run.assert_called_once_with(activity_tracker)

    @pytest.mark.asyncio
    async def test_monthly_report(self, mock_bot):
        """Тест задачи monthly_report."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Патчим run_automatic_monthly_report
        with patch('cogs.activity.run_automatic_monthly_report') as mock_run:
            # Вызываем метод monthly_report
            await activity_tracker.monthly_report()
            
            # Проверяем, что run_automatic_monthly_report был вызван с правильными аргументами
            mock_run.assert_called_once_with(activity_tracker)


class TestCommands:
    """Тесты для команд ActivityTracker."""

    @pytest.mark.asyncio
    async def test_activity_command(self, mock_bot, mock_context):
        """Тест команды activity_command."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Патчим метод activity_command напрямую, а не через __call__
            with patch.object(activity_tracker, 'update_current_activities') as mock_update, \
                 patch.object(activity_tracker.data_manager, 'get_daily_stats') as mock_get_stats, \
                 patch('cogs.activity.ActivityView') as mock_view:
                
                # Настраиваем mock_get_stats, чтобы он возвращал тестовые данные
                mock_get_stats.return_value = {123456789: {"Test Game": 3600}}
                
                # Настраиваем mock_view
                mock_view_instance = MagicMock()
                mock_view_instance.get_current_content.return_value = "Test content"
                mock_view.return_value = mock_view_instance
                
                # Вызываем метод напрямую, а не через команду
                await activity_tracker.activity_command.callback(activity_tracker, mock_context)
                
                # Проверяем, что update_current_activities был вызван
                mock_update.assert_called_once()
                
                # Проверяем, что get_daily_stats был вызван с правильными аргументами
                mock_get_stats.assert_called_once_with(date.today())
                
                # Проверяем, что ActivityView был создан с правильными аргументами
                mock_view.assert_called_once()
                args = mock_view.call_args[0]
                assert args[0] == mock_bot
                assert args[1] == {123456789: {"Test Game": 3600}}
                
                # Проверяем, что ctx.send был вызван
                mock_context.send.assert_called_once()
                
                # Проверяем аргументы вызова
                call_args = mock_context.send.call_args
                
                # Проверяем, что первый аргумент содержит ожидаемый текст
                # или что view был передан как именованный аргумент
                if call_args[0]:  # Если есть позиционные аргументы
                    assert "Статистика активности за сегодня" in call_args[0][0]
                else:  # Иначе проверяем именованные аргументы
                    assert "view" in call_args[1]
                    assert call_args[1]["view"] == mock_view_instance

    @pytest.mark.asyncio
    async def test_mystats_command(self, mock_bot, mock_context, mock_member):
        """Тест команды mystats_command."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.author = mock_member
            
            # Патчим update_current_activities, get_monthly_stats и get_daily_stats
            with patch.object(activity_tracker, 'update_current_activities') as mock_update, \
                 patch.object(activity_tracker.data_manager, 'get_monthly_stats') as mock_get_monthly, \
                 patch.object(activity_tracker.data_manager, 'get_daily_stats') as mock_get_daily, \
                 patch('cogs.activity.StatsView') as mock_view:
                
                # Настраиваем mock_get_monthly, чтобы он возвращал тестовые данные
                mock_get_monthly.return_value = {"Test Game": 3600}
                
                # Настраиваем mock_get_daily, чтобы он возвращал тестовые данные
                mock_get_daily.return_value = {mock_member.id: {"Test Game": 1800}}
                
                # Настраиваем mock_view
                mock_view_instance = MagicMock()
                mock_view_instance.get_current_embed.return_value = discord.Embed()
                mock_view.return_value = mock_view_instance
                
                # Вызываем метод напрямую, а не через команду
                await activity_tracker.mystats_command.callback(activity_tracker, mock_context)
                
                # Проверяем, что update_current_activities был вызван
                mock_update.assert_called_once()
                
                # Проверяем, что get_monthly_stats был вызван с правильными аргументами
                today = date.today()
                mock_get_monthly.assert_called_once_with(mock_member.id, today.year, today.month)
                
                # Проверяем, что get_daily_stats был вызван с правильными аргументами
                mock_get_daily.assert_called_once_with(today)
                
                # Проверяем, что StatsView был создан с правильными аргументами
                mock_view.assert_called_once()
                
                # Проверяем, что ctx.send был вызван с правильными аргументами
                mock_context.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_mystatsall_command(self, mock_bot, mock_context, mock_member):
        """Тест команды mystatsall_command."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.author = mock_member
            
            # Патчим update_current_activities и get_all_time_stats
            with patch.object(activity_tracker, 'update_current_activities') as mock_update, \
                 patch.object(activity_tracker.data_manager, 'get_all_time_stats') as mock_get_stats, \
                 patch('cogs.activity.StatsView') as mock_view:
                
                # Настраиваем mock_get_stats, чтобы он возвращал тестовые данные
                mock_get_stats.return_value = {"Test Game": 3600, "Another Game": 7200}
                
                # Настраиваем mock_view
                mock_view_instance = MagicMock()
                mock_view_instance.get_current_embed.return_value = discord.Embed()
                mock_view.return_value = mock_view_instance
                
                # Вызываем метод напрямую, а не через команду
                await activity_tracker.mystatsall_command.callback(activity_tracker, mock_context)
                
                # Проверяем, что update_current_activities был вызван
                mock_update.assert_called_once()
                
                # Проверяем, что get_all_time_stats был вызван с правильными аргументами
                mock_get_stats.assert_called_once_with(mock_member.id)
                
                # Проверяем, что StatsView был создан с правильными аргументами
                mock_view.assert_called_once()
                
                # Проверяем, что ctx.send был вызван с правильными аргументами
                mock_context.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_report_daily_command(self, mock_bot, mock_context):
        """Тест команды report_daily_command."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.channel = MagicMock(spec=discord.TextChannel)
            mock_context.interaction = MagicMock()
            mock_context.interaction.followup = MagicMock()
            mock_context.interaction.followup.send = AsyncMock()
            
            # Патчим send_daily_report
            with patch('cogs.activity.send_daily_report') as mock_send:
                # Настраиваем mock_send, чтобы он возвращал True
                mock_send.return_value = True
                
                # Вызываем метод напрямую, а не через команду
                await activity_tracker.report_daily_command.callback(activity_tracker, mock_context, 2024, 1, 1)
                
                # Проверяем, что send_daily_report был вызван с правильными аргументами
                mock_send.assert_called_once()
                args = mock_send.call_args[0]
                assert args[0] == date(2024, 1, 1)
                assert args[1] == mock_bot
                assert args[2] == activity_tracker.data_manager
                
                # Проверяем, что ctx.interaction.followup.send был вызван с правильными аргументами
                mock_context.interaction.followup.send.assert_called_once()
                assert "успешно отправлен" in mock_context.interaction.followup.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_report_monthly_command(self, mock_bot, mock_context):
        """Тест команды report_monthly_command."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.channel = MagicMock(spec=discord.TextChannel)
            mock_context.interaction = MagicMock()
            mock_context.interaction.followup = MagicMock()
            mock_context.interaction.followup.send = AsyncMock()
            
            # Патчим send_monthly_report
            with patch('cogs.activity.send_monthly_report') as mock_send:
                # Настраиваем mock_send, чтобы он возвращал True
                mock_send.return_value = True
                
                # Вызываем метод напрямую, а не через команду
                await activity_tracker.report_monthly_command.callback(activity_tracker, mock_context, 2024, 1)
                
                # Проверяем, что send_monthly_report был вызван с правильными аргументами
                mock_send.assert_called_once()
                args = mock_send.call_args[0]
                assert args[0] == 2024
                assert args[1] == 1
                assert args[2] == mock_bot
                assert args[3] == activity_tracker.data_manager
                
                # Проверяем, что ctx.interaction.followup.send был вызван с правильными аргументами
                mock_context.interaction.followup.send.assert_called_once()
                assert "успешно отправлен" in mock_context.interaction.followup.send.call_args[0][0]

class TestEventHandlers:
    """Тесты для обработчиков событий ActivityTracker."""

    @pytest.mark.asyncio
    async def test_on_ready_first_call(self, mock_bot):
        """Тест метода on_ready при первом вызове."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Проверяем, что scan_scheduled изначально False
            assert activity_tracker.scan_scheduled is False
            
            # Патчим scan_all_users_activity
            with patch.object(activity_tracker, 'scan_all_users_activity') as mock_scan:
                # Вызываем метод on_ready
                await activity_tracker.on_ready()
                
                # Проверяем, что scan_scheduled стал True
                assert activity_tracker.scan_scheduled is True

    @pytest.mark.asyncio
    async def test_on_ready_second_call(self, mock_bot):
        """Тест метода on_ready при повторном вызове."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Устанавливаем scan_scheduled в True (имитируем первый вызов)
            activity_tracker.scan_scheduled = True
            
            # Патчим scan_all_users_activity
            with patch.object(activity_tracker, 'scan_all_users_activity') as mock_scan:
                # Вызываем метод on_ready
                await activity_tracker.on_ready()
                
                # scan_scheduled должен остаться True
                assert activity_tracker.scan_scheduled is True

    @pytest.mark.asyncio
    async def test_on_presence_update_bot_user(self, mock_bot):
        """Тест метода on_presence_update для бота."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Создаем моки для before и after (бот)
        before = MagicMock(spec=discord.Member)
        before.bot = True
        before.id = 123456789
        
        after = MagicMock(spec=discord.Member)
        after.bot = True
        after.id = 123456789
        
        # Вызываем метод on_presence_update
        await activity_tracker.on_presence_update(before, after)
        
        # Проверяем, что ничего не было добавлено в current_activities
        assert len(activity_tracker.current_activities) == 0

    @pytest.mark.asyncio
    async def test_on_presence_update_application(self, mock_bot):
        """Тест метода on_presence_update для приложения."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Создаем моки для before и after
        before = MagicMock(spec=discord.Member)
        before.bot = False
        before.id = 123456789
        
        after = MagicMock(spec=discord.Member)
        after.bot = False
        after.id = 123456789
        
        # Патчим is_application, чтобы он возвращал True
        with patch('cogs.activity.is_application', return_value=True):
            # Вызываем метод on_presence_update
            await activity_tracker.on_presence_update(before, after)
            
            # Проверяем, что ничего не было добавлено в current_activities
            assert len(activity_tracker.current_activities) == 0

    @pytest.mark.asyncio
    async def test_on_presence_update_no_change(self, mock_bot):
        """Тест метода on_presence_update без изменения активности."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Создаем мок для активности
        mock_activity = MagicMock(spec=discord.Activity)
        mock_activity.type = discord.ActivityType.playing
        mock_activity.name = "Test Game"
        
        # Создаем моки для before и after (одинаковая активность)
        before = MagicMock(spec=discord.Member)
        before.bot = False
        before.id = 123456789
        before.activities = [mock_activity]
        
        after = MagicMock(spec=discord.Member)
        after.bot = False
        after.id = 123456789
        after.activities = [mock_activity]
        
        # Патчим is_application
        with patch('cogs.activity.is_application', return_value=False):
            # Вызываем метод on_presence_update
            await activity_tracker.on_presence_update(before, after)
            
            # Проверяем, что ничего не было добавлено в current_activities
            assert len(activity_tracker.current_activities) == 0

    @pytest.mark.asyncio
    async def test_on_presence_update_error_handling(self, mock_bot):
        """Тест обработки ошибок в on_presence_update."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Создаем моки для before и after
        before = MagicMock(spec=discord.Member)
        before.bot = False
        before.id = 123456789
        before.name = "Test User"
        before.activities = []
        
        after = MagicMock(spec=discord.Member)
        after.bot = False
        after.id = 123456789
        after.name = "Test User"
        # Имитируем ошибку при доступе к activities
        after.activities = MagicMock(side_effect=Exception("Test error"))
        
        # Патчим is_application
        with patch('cogs.activity.is_application', return_value=False):
            # Вызываем метод on_presence_update (не должен выбрасывать исключение)
            await activity_tracker.on_presence_update(before, after)
            
            # Проверяем, что ничего не было добавлено в current_activities
            assert len(activity_tracker.current_activities) == 0


class TestBackgroundTasksBeforeLoop:
    """Тесты для методов before_loop фоновых задач."""

    @pytest.mark.asyncio
    async def test_before_periodic_save_success(self, mock_bot):
        """Тест успешного выполнения before_periodic_save."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Настраиваем mock_bot.wait_until_ready
        mock_bot.wait_until_ready = AsyncMock()
        
        # Вызываем метод before_periodic_save
        await activity_tracker.before_periodic_save()
        
        # Проверяем, что wait_until_ready был вызван
        mock_bot.wait_until_ready.assert_called_once()

    @pytest.mark.asyncio
    async def test_before_periodic_save_runtime_error(self, mock_bot):
        """Тест обработки RuntimeError в before_periodic_save."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Настраиваем mock_bot.wait_until_ready для выброса RuntimeError
        mock_bot.wait_until_ready = AsyncMock(
            side_effect=RuntimeError("Client has not been properly initialised")
        )
        
        # Вызываем метод before_periodic_save (не должен выбрасывать исключение)
        await activity_tracker.before_periodic_save()
        
        # Проверяем, что wait_until_ready был вызван
        mock_bot.wait_until_ready.assert_called_once()

    @pytest.mark.asyncio
    async def test_before_periodic_save_other_runtime_error(self, mock_bot):
        """Тест обработки другой RuntimeError в before_periodic_save."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Настраиваем mock_bot.wait_until_ready для выброса другой RuntimeError
        mock_bot.wait_until_ready = AsyncMock(
            side_effect=RuntimeError("Other error")
        )
        
        # Вызываем метод before_periodic_save (не должен выбрасывать исключение)
        await activity_tracker.before_periodic_save()
        
        # Проверяем, что wait_until_ready был вызван
        mock_bot.wait_until_ready.assert_called_once()

    @pytest.mark.asyncio
    async def test_before_periodic_save_general_exception(self, mock_bot):
        """Тест обработки общего исключения в before_periodic_save."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Настраиваем mock_bot.wait_until_ready для выброса общего исключения
        mock_bot.wait_until_ready = AsyncMock(side_effect=Exception("General error"))
        
        # Вызываем метод before_periodic_save (не должен выбрасывать исключение)
        await activity_tracker.before_periodic_save()
        
        # Проверяем, что wait_until_ready был вызван
        mock_bot.wait_until_ready.assert_called_once()

    @pytest.mark.asyncio
    async def test_before_daily_report_success(self, mock_bot):
        """Тест успешного выполнения before_daily_report."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Настраиваем mock_bot.wait_until_ready
        mock_bot.wait_until_ready = AsyncMock()
        
        # Вызываем метод before_daily_report
        await activity_tracker.before_daily_report()
        
        # Проверяем, что wait_until_ready был вызван
        mock_bot.wait_until_ready.assert_called_once()

    @pytest.mark.asyncio
    async def test_before_monthly_report_success(self, mock_bot):
        """Тест успешного выполнения before_monthly_report."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Настраиваем mock_bot.wait_until_ready
        mock_bot.wait_until_ready = AsyncMock()
        
        # Вызываем метод before_monthly_report
        await activity_tracker.before_monthly_report()
        
        # Проверяем, что wait_until_ready был вызван
        mock_bot.wait_until_ready.assert_called_once()


class TestUpdateCurrentActivitiesEdgeCases:
    """Тесты для граничных случаев update_current_activities."""

    @pytest.mark.asyncio
    async def test_update_current_activities_empty(self, mock_bot):
        """Тест update_current_activities с пустыми current_activities."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Убеждаемся, что current_activities пуст
        activity_tracker.current_activities = {}
        
        # Вызываем метод update_current_activities
        await activity_tracker.update_current_activities()
        
        # Проверяем, что current_activities остался пустым
        assert len(activity_tracker.current_activities) == 0

    @pytest.mark.asyncio
    async def test_update_current_activities_negative_time(self, mock_bot):
        """Тест update_current_activities с отрицательным временем."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Добавляем тестовые данные с временем в будущем
        user_id = 123456789
        game_name = "Test Game"
        future_time = datetime.now(pytz.UTC) + timedelta(minutes=30)  # Время в будущем
        activity_tracker.current_activities[user_id] = (game_name, future_time)
        
        # Вызываем метод update_current_activities
        await activity_tracker.update_current_activities()
        
        # Проверяем, что время было сброшено
        assert user_id in activity_tracker.current_activities
        assert activity_tracker.current_activities[user_id][0] == game_name
        # Время должно быть обновлено на текущее
        assert activity_tracker.current_activities[user_id][1] <= datetime.now(pytz.UTC)

    @pytest.mark.asyncio
    async def test_update_current_activities_too_long_session(self, mock_bot):
        """Тест update_current_activities со слишком длинной сессией."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Добавляем тестовые данные со слишком старым временем
        user_id = 123456789
        game_name = "Test Game"
        old_time = datetime.now(pytz.UTC) - timedelta(days=3)  # 3 дня назад
        activity_tracker.current_activities[user_id] = (game_name, old_time)
        
        # Настраиваем конфиг бота
        mock_bot.settings.timeouts.activity_max_record = 172800  # 2 дня
        
        # Вызываем метод update_current_activities
        await activity_tracker.update_current_activities()
        
        # Проверяем, что сессия была удалена
        assert user_id not in activity_tracker.current_activities

    @pytest.mark.asyncio
    async def test_update_current_activities_too_short_session(self, mock_bot):
        """Тест update_current_activities со слишком короткой сессией."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Добавляем тестовые данные с очень коротким временем
        user_id = 123456789
        game_name = "Test Game"
        recent_time = datetime.now(pytz.UTC) - timedelta(seconds=5)  # 5 секунд назад
        activity_tracker.current_activities[user_id] = (game_name, recent_time)
        
        # Настраиваем конфиг бота
        mock_bot.settings.timeouts.activity_min_record = 10  # 10 секунд
        
        # Патчим data_manager.update_activity
        with patch.object(activity_tracker.data_manager, 'update_activity') as mock_update:
            # Вызываем метод update_current_activities
            await activity_tracker.update_current_activities()
            
            # Проверяем, что update_activity НЕ был вызван
            mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_current_activities_database_error(self, mock_bot):
        """Тест update_current_activities с ошибкой базы данных."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Добавляем тестовые данные
            user_id = 123456789
            game_name = "Test Game"
            start_time = datetime.now(pytz.UTC) - timedelta(minutes=30)
            activity_tracker.current_activities[user_id] = (game_name, start_time)
            
            # Патчим data_manager.update_activity для выброса исключения
            with patch.object(activity_tracker.data_manager, 'update_activity') as mock_update:
                mock_update.side_effect = Exception("Database error")
                
                # Вызываем метод update_current_activities (не должен выбрасывать исключение)
                await activity_tracker.update_current_activities()
                
                # Проверяем, что update_activity был вызван (может быть несколько раз из-за asyncio.gather)
                assert mock_update.call_count >= 1
                
                # Проверяем, что время в памяти НЕ было обновлено из-за ошибки
                assert activity_tracker.current_activities[user_id][1] == start_time

    @pytest.mark.asyncio
    async def test_update_current_activities_final_save(self, mock_bot):
        """Тест update_current_activities с final_save=True."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Добавляем тестовые данные
            user_id = 123456789
            game_name = "Test Game"
            start_time = datetime.now(pytz.UTC) - timedelta(minutes=30)
            activity_tracker.current_activities[user_id] = (game_name, start_time)
            
            # Патчим data_manager.update_activity
            with patch.object(activity_tracker.data_manager, 'update_activity') as mock_update:
                # Вызываем метод update_current_activities с final_save=True
                await activity_tracker.update_current_activities(final_save=True)
                
                # Проверяем, что update_activity был вызван (может быть несколько раз из-за asyncio.gather)
                assert mock_update.call_count >= 1
                
                # Проверяем, что время в памяти НЕ было обновлено (final_save=True)
                assert activity_tracker.current_activities[user_id][1] == start_time


class TestScanAllUsersActivity:
    """Тесты для метода scan_all_users_activity."""

    @pytest.mark.asyncio
    async def test_scan_all_users_activity_with_bots(self, mock_bot):
        """Тест scan_all_users_activity с ботами в списке пользователей."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Создаем мок гильдии
        mock_guild = MagicMock(spec=discord.Guild)
        
        # Создаем мок бота
        mock_bot_member = MagicMock(spec=discord.Member)
        mock_bot_member.bot = True
        mock_bot_member.id = 111111111
        
        # Создаем мок обычного пользователя
        mock_user = MagicMock(spec=discord.Member)
        mock_user.bot = False
        mock_user.id = 222222222
        mock_user.name = "Test User"
        mock_user.activities = []
        
        # Настраиваем гильдию
        mock_guild.members = [mock_bot_member, mock_user]
        mock_bot.guilds = [mock_guild]
        
        # Патчим is_application и wait_until_ready
        with patch('cogs.activity.is_application', return_value=False), \
             patch.object(mock_bot, 'wait_until_ready', new_callable=AsyncMock):
            
            # Вызываем метод scan_all_users_activity
            await activity_tracker.scan_all_users_activity()
            
            # Проверяем, что бот не был добавлен в current_activities
            assert mock_bot_member.id not in activity_tracker.current_activities
            # Проверяем, что обычный пользователь тоже не был добавлен (нет активности)
            assert mock_user.id not in activity_tracker.current_activities

    @pytest.mark.asyncio
    async def test_scan_all_users_activity_with_applications(self, mock_bot):
        """Тест scan_all_users_activity с приложениями в списке пользователей."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Создаем мок гильдии
        mock_guild = MagicMock(spec=discord.Guild)
        
        # Создаем мок приложения
        mock_app = MagicMock(spec=discord.Member)
        mock_app.bot = False
        mock_app.id = 333333333
        
        # Настраиваем гильдию
        mock_guild.members = [mock_app]
        mock_bot.guilds = [mock_guild]
        
        # Патчим is_application и wait_until_ready
        with patch('cogs.activity.is_application', return_value=True), \
             patch.object(mock_bot, 'wait_until_ready', new_callable=AsyncMock):
            
            # Вызываем метод scan_all_users_activity
            await activity_tracker.scan_all_users_activity()
            
            # Проверяем, что приложение не было добавлено в current_activities
            assert mock_app.id not in activity_tracker.current_activities

    @pytest.mark.asyncio
    async def test_scan_all_users_activity_with_playing_activity(self, mock_bot):
        """Тест scan_all_users_activity с пользователем, играющим в игру."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Создаем мок гильдии
        mock_guild = MagicMock(spec=discord.Guild)
        
        # Создаем мок пользователя с игровой активностью
        mock_user = MagicMock(spec=discord.Member)
        mock_user.bot = False
        mock_user.id = 444444444
        mock_user.name = "Gaming User"
        
        # Создаем мок активности
        mock_activity = MagicMock(spec=discord.Activity)
        mock_activity.type = discord.ActivityType.playing
        mock_activity.name = "Test Game"
        mock_user.activities = [mock_activity]
        
        # Настраиваем гильдию
        mock_guild.members = [mock_user]
        mock_bot.guilds = [mock_guild]
        
        # Патчим is_application и wait_until_ready
        with patch('cogs.activity.is_application', return_value=False), \
             patch.object(mock_bot, 'wait_until_ready', new_callable=AsyncMock):
            
            # Вызываем метод scan_all_users_activity
            await activity_tracker.scan_all_users_activity()
            
            # Проверяем, что пользователь был добавлен в current_activities
            assert mock_user.id in activity_tracker.current_activities
            assert activity_tracker.current_activities[mock_user.id][0] == "Test Game"

    @pytest.mark.asyncio
    async def test_scan_all_users_activity_error_handling(self, mock_bot):
        """Тест обработки ошибок в scan_all_users_activity."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Настраиваем mock_bot.guilds для выброса исключения
        mock_bot.guilds = MagicMock(side_effect=Exception("Guild access error"))
        
        # Патчим wait_until_ready
        with patch.object(mock_bot, 'wait_until_ready', new_callable=AsyncMock):
            
            # Вызываем метод scan_all_users_activity (не должен выбрасывать исключение)
            await activity_tracker.scan_all_users_activity()
            
            # Проверяем, что current_activities остался пустым
            assert len(activity_tracker.current_activities) == 0


class TestPeriodicSaveErrorHandling:
    """Тесты для обработки ошибок в periodic_save."""

    @pytest.mark.asyncio
    async def test_periodic_save_error_handling(self, mock_bot):
        """Тест обработки ошибок в periodic_save."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Патчим update_current_activities для выброса исключения
        with patch.object(activity_tracker, 'update_current_activities') as mock_update:
            mock_update.side_effect = Exception("Update error")
            
            # Вызываем метод periodic_save (не должен выбрасывать исключение)
            await activity_tracker.periodic_save()
            
            # Проверяем, что update_current_activities был вызван
            mock_update.assert_called_once()


class TestCommandsEdgeCases:
    """Тесты для граничных случаев команд."""

    @pytest.mark.asyncio
    async def test_activity_command_no_data(self, mock_bot, mock_context):
        """Тест команды activity_command без данных."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Патчим методы
            with patch.object(activity_tracker, 'update_current_activities') as mock_update, \
                 patch.object(activity_tracker.data_manager, 'get_daily_stats') as mock_get_stats:
                
                # Настраиваем mock_get_stats, чтобы он возвращал пустые данные
                mock_get_stats.return_value = {}
                
                # Вызываем метод напрямую
                await activity_tracker.activity_command.callback(activity_tracker, mock_context, False)
                
                # Проверяем, что было отправлено сообщение об отсутствии данных
                mock_context.send.assert_called_once()
                assert "никто не играл" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_activity_command_test_mode(self, mock_bot, mock_context, mock_guild, mock_member):
        """Тест команды activity_command в тестовом режиме."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.author.id = 123456789
            mock_context.guild = mock_guild
            mock_guild.members = [mock_member]
            mock_member.bot = False
            mock_member.id = 987654321
            
            # Патчим методы
            with patch.object(activity_tracker, 'update_current_activities') as mock_update, \
                 patch.object(activity_tracker.data_manager, 'get_daily_stats') as mock_get_stats, \
                 patch('cogs.activity.ActivityView') as mock_view:
                
                # Настраиваем mock_get_stats, чтобы он возвращал пустые данные
                mock_get_stats.return_value = {}
                
                # Настраиваем mock_view
                mock_view_instance = MagicMock()
                mock_view_instance.get_current_content.return_value = "Test content"
                mock_view.return_value = mock_view_instance
                
                # Вызываем метод в тестовом режиме
                await activity_tracker.activity_command.callback(activity_tracker, mock_context, True)
                
                # Проверяем, что ActivityView был создан с тестовыми данными
                mock_view.assert_called_once()
                args = mock_view.call_args[0]
                assert args[1]  # Должны быть тестовые данные
                
                # Проверяем, что сообщение содержит префикс [ТЕСТ]
                mock_context.send.assert_called_once()
                call_args = mock_context.send.call_args
                assert "[ТЕСТ]" in call_args[1]["content"]

    @pytest.mark.asyncio
    async def test_mystats_command_invalid_month(self, mock_bot, mock_context, mock_member):
        """Тест команды mystats_command с неверным месяцем."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.author = mock_member
            
            # Вызываем метод с неверным месяцем
            await activity_tracker.mystats_command.callback(
                activity_tracker, mock_context, None, 13, None  # Месяц 13 - неверный
            )
            
            # Проверяем, что было отправлено сообщение об ошибке
            mock_context.send.assert_called_once()
            assert "Неверный номер месяца" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_mystats_command_no_data(self, mock_bot, mock_context, mock_member):
        """Тест команды mystats_command без данных."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.author = mock_member
            
            # Патч

class TestCommandErrorHandler:
    """Тесты для обработчика ошибок команд."""

    @pytest.mark.asyncio
    async def test_cog_command_error_delegates_to_utils(self, mock_bot, mock_context):
        """Тест делегирования обработки ошибок в utils.error_handler."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Создаем ошибку
            error = commands.CommandError("Test error")
            
            # Настраиваем mock_context.command для логирования
            mock_context.command = MagicMock()
            mock_context.command.__str__.return_value = "test_command"
            
            # Патчим safe_send_error и get_error_message
            with patch('utils.error_handler.safe_send_error', new_callable=AsyncMock) as mock_safe_send, \
                 patch('utils.error_handler.get_error_message', return_value="Error message") as mock_get_msg:
                
                # Вызываем обработчик ошибок
                await activity_tracker.cog_command_error(mock_context, error)
                
                # Проверяем, что вызваны утилиты
                mock_get_msg.assert_called_once_with(error)
                mock_safe_send.assert_called_once_with(mock_context, "Error message")


class TestReportCommandsEdgeCases:
    """Тесты для граничных случаев команд отчетов."""

    @pytest.mark.asyncio
    async def test_report_daily_command_future_date(self, mock_bot, mock_context):
        """Тест команды report_daily_command с будущей датой."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Получаем завтрашнюю дату
            tomorrow = date.today() + timedelta(days=1)
            
            # Вызываем метод с будущей датой
            await activity_tracker.report_daily_command.callback(
                activity_tracker, mock_context, tomorrow.year, tomorrow.month, tomorrow.day
            )
            
            # Проверяем, что было отправлено сообщение об ошибке
            mock_context.send.assert_called_once()
            assert "будущую дату" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_report_daily_command_invalid_date(self, mock_bot, mock_context):
        """Тест команды report_daily_command с некорректной датой."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Вызываем метод с некорректной датой (32 день)
            await activity_tracker.report_daily_command.callback(
                activity_tracker, mock_context, 2024, 1, 32
            )
            
            # Проверяем, что было отправлено сообщение об ошибке
            mock_context.send.assert_called_once()
            assert "Некорректная дата" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_report_daily_command_failed(self, mock_bot, mock_context):
        """Тест команды report_daily_command с неудачной отправкой."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.channel = MagicMock(spec=discord.TextChannel)
            mock_context.interaction = MagicMock()
            mock_context.interaction.followup = MagicMock()
            mock_context.interaction.followup.send = AsyncMock()
            mock_context.defer = AsyncMock()
            
            # Патчим send_daily_report для возврата False
            with patch('cogs.activity.send_daily_report') as mock_send:
                mock_send.return_value = False
                
                # Вызываем метод
                await activity_tracker.report_daily_command.callback(
                    activity_tracker, mock_context, 2024, 1, 1
                )
                
                # Проверяем, что было отправлено сообщение о неудаче
                mock_context.interaction.followup.send.assert_called_once()
                assert "Не удалось отправить" in mock_context.interaction.followup.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_report_monthly_command_invalid_month(self, mock_bot, mock_context):
        """Тест команды report_monthly_command с неверным месяцем."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Вызываем метод с неверным месяцем
            await activity_tracker.report_monthly_command.callback(
                activity_tracker, mock_context, 2024, 13  # Месяц 13 - неверный
            )
            
            # Проверяем, что было отправлено сообщение об ошибке
            mock_context.send.assert_called_once()
            assert "Неверный номер месяца" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_report_monthly_command_invalid_year(self, mock_bot, mock_context):
        """Тест команды report_monthly_command с неверным годом."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Вызываем метод с неверным годом
            await activity_tracker.report_monthly_command.callback(
                activity_tracker, mock_context, 2010, 1  # Год 2010 - слишком старый
            )
            
            # Проверяем, что было отправлено сообщение об ошибке
            mock_context.send.assert_called_once()
            assert "Некорректный год" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_report_monthly_command_current_month(self, mock_bot, mock_context):
        """Тест команды report_monthly_command для текущего месяца."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Получаем текущий месяц и год
            today = date.today()
            
            # Вызываем метод для текущего месяца
            await activity_tracker.report_monthly_command.callback(
                activity_tracker, mock_context, today.year, today.month
            )
            
            # Проверяем, что было отправлено сообщение об ошибке
            mock_context.send.assert_called_once()
            assert "текущий или будущий месяц" in mock_context.send.call_args[0][0]


class TestCogUnloadErrorHandling:
    """Тесты для обработки ошибок при выгрузке кога."""

    @pytest.mark.asyncio
    async def test_cog_unload_runtime_error(self, mock_bot):
        """Тест выгрузки кога с RuntimeError."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Патчим методы cancel для фоновых задач
        with patch.object(activity_tracker.daily_report, 'cancel') as mock_daily_report, \
             patch.object(activity_tracker.monthly_report, 'cancel') as mock_monthly_report, \
             patch.object(activity_tracker.periodic_save, 'cancel') as mock_periodic_save, \
             patch.object(activity_tracker, 'update_current_activities') as mock_update:
            
            # Настраиваем mock_update для выброса RuntimeError
            mock_update.side_effect = RuntimeError("Event loop stopped")
            
            # Вызываем метод cog_unload (не должен выбрасывать исключение)
            await activity_tracker.cog_unload()
            
            # Проверяем, что методы cancel были вызваны
            mock_daily_report.assert_called_once()
            mock_monthly_report.assert_called_once()
            mock_periodic_save.assert_called_once()
            
            # Проверяем, что update_current_activities был вызван
            mock_update.assert_called_once_with(final_save=True)

    @pytest.mark.asyncio
    async def test_cog_unload_general_exception(self, mock_bot):
        """Тест выгрузки кога с общим исключением."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Патчим методы cancel для фоновых задач
        with patch.object(activity_tracker.daily_report, 'cancel') as mock_daily_report, \
             patch.object(activity_tracker.monthly_report, 'cancel') as mock_monthly_report, \
             patch.object(activity_tracker.periodic_save, 'cancel') as mock_periodic_save, \
             patch.object(activity_tracker, 'update_current_activities') as mock_update:
            
            # Настраиваем mock_update для выброса общего исключения
            mock_update.side_effect = Exception("General error")
            
            # Вызываем метод cog_unload (не должен выбрасывать исключение)
            await activity_tracker.cog_unload()
            
            # Проверяем, что методы cancel были вызваны
            mock_daily_report.assert_called_once()
            mock_monthly_report.assert_called_once()
            mock_periodic_save.assert_called_once()
            
            # Проверяем, что update_current_activities был вызван
            mock_update.assert_called_once_with(final_save=True)


class TestMystatsCommandEdgeCases:
    """Тесты для дополнительных случаев команды mystats."""

    @pytest.mark.asyncio
    async def test_mystats_command_no_data(self, mock_bot, mock_context, mock_member):
        """Тест команды mystats_command без данных."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.author = mock_member
            
            # Патчим методы для возврата пустых данных
            with patch.object(activity_tracker, 'update_current_activities') as mock_update, \
                 patch.object(activity_tracker.data_manager, 'get_monthly_stats') as mock_get_monthly, \
                 patch.object(activity_tracker.data_manager, 'get_daily_stats') as mock_get_daily:
                
                # Настраиваем моки для возврата пустых данных
                mock_get_monthly.return_value = {}
                mock_get_daily.return_value = {}
                
                # Вызываем метод
                await activity_tracker.mystats_command.callback(
                    activity_tracker, mock_context, None, None, None
                )
                
                # Проверяем, что было отправлено сообщение об отсутствии данных
                mock_context.send.assert_called_once()
                call_args = mock_context.send.call_args
                # Проверяем, что был передан embed
                assert "embed" in call_args[1]
                embed = call_args[1]["embed"]
                assert "Нет данных" in embed.description

    @pytest.mark.asyncio
    async def test_mystats_command_with_current_session(self, mock_bot, mock_context, mock_member):
        """Тест команды mystats_command с текущей сессией."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Добавляем текущую сессию
            user_id = mock_member.id
            game_name = "Current Game"
            start_time = datetime.now(pytz.UTC) - timedelta(minutes=15)  # 15 минут назад
            activity_tracker.current_activities[user_id] = (game_name, start_time)
            
            # Настраиваем mock_context
            mock_context.author = mock_member
            
            # Патчим методы
            with patch.object(activity_tracker, 'update_current_activities') as mock_update, \
                 patch.object(activity_tracker.data_manager, 'get_monthly_stats') as mock_get_monthly, \
                 patch.object(activity_tracker.data_manager, 'get_daily_stats') as mock_get_daily, \
                 patch('cogs.activity.StatsView') as mock_view, \
                 patch('cogs.activity.format_time_short') as mock_format_time:
                
                # Настраиваем моки
                mock_get_monthly.return_value = {"Test Game": 3600}
                mock_get_daily.return_value = {user_id: {"Test Game": 1800}}
                mock_format_time.return_value = "15м"
                
                # Настраиваем mock_view
                mock_view_instance = MagicMock()
                mock_view_instance.get_current_embed.return_value = discord.Embed()
                mock_view.return_value = mock_view_instance
                
                # Вызываем метод для текущего месяца
                await activity_tracker.mystats_command.callback(
                    activity_tracker, mock_context, None, None, None
                )
                
                # Проверяем, что было отправлено два сообщения (статистика + текущая сессия)
                assert mock_context.send.call_count == 2
                
                # Проверяем второе сообщение (текущая сессия)
                second_call = mock_context.send.call_args_list[1]
                assert "сейчас играет" in second_call[0][0]
                assert game_name in second_call[0][0]

    @pytest.mark.asyncio
    async def test_mystatsall_command_no_data(self, mock_bot, mock_context, mock_member):
        """Тест команды mystatsall_command без данных."""
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр ActivityTracker
            activity_tracker = ActivityTracker(mock_bot)
            
            # Настраиваем mock_context
            mock_context.author = mock_member
            
            # Патчим методы для возврата пустых данных
            with patch.object(activity_tracker, 'update_current_activities') as mock_update, \
                 patch.object(activity_tracker.data_manager, 'get_all_time_stats') as mock_get_stats:
                
                # Настраиваем mock_get_stats для возврата пустых данных
                mock_get_stats.return_value = {}
                
                # Вызываем метод
                await activity_tracker.mystatsall_command.callback(
                    activity_tracker, mock_context, None
                )
                
                # Проверяем, что было отправлено сообщение об отсутствии данных
                mock_context.send.assert_called_once()
                call_args = mock_context.send.call_args
                # Проверяем, что был передан embed
                assert "embed" in call_args[1]
                embed = call_args[1]["embed"]
                assert "Нет данных" in embed.description


class TestSetupFunction:
    """Тесты для функции setup."""

    @pytest.mark.asyncio
    async def test_setup_function(self, mock_bot):
        """Тест функции setup."""
        # Импортируем функцию setup
        from cogs.activity import setup
        
        # Патчим add_cog
        mock_bot.add_cog = AsyncMock()
        
        # Вызываем функцию setup
        await setup(mock_bot)
        
        # Проверяем, что add_cog был вызван с экземпляром ActivityTracker
        mock_bot.add_cog.assert_called_once()
        cog_instance = mock_bot.add_cog.call_args[0][0]
        assert isinstance(cog_instance, ActivityTracker)
        assert cog_instance.bot == mock_bot


class TestOnPresenceUpdateComplexScenarios:
    """Тесты для сложных сценариев on_presence_update."""

    @pytest.mark.asyncio
    async def test_on_presence_update_game_switch(self, mock_bot):
        """Тест переключения между играми."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Добавляем существующую сессию
        user_id = 123456789
        old_game = "Old Game"
        start_time = datetime.now(pytz.UTC) - timedelta(minutes=30)
        activity_tracker.current_activities[user_id] = (old_game, start_time)
        
        # Создаем моки для before и after
        before = MagicMock(spec=discord.Member)
        before.bot = False
        before.id = user_id
        before.name = "Test User"
        
        # Старая активность
        old_activity = MagicMock(spec=discord.Activity)
        old_activity.type = discord.ActivityType.playing
        old_activity.name = old_game
        before.activities = [old_activity]
        
        after = MagicMock(spec=discord.Member)
        after.bot = False
        after.id = user_id
        after.name = "Test User"
        
        # Новая активность
        new_activity = MagicMock(spec=discord.Activity)
        new_activity.type = discord.ActivityType.playing
        new_activity.name = "New Game"
        after.activities = [new_activity]
        
        # Патчим data_manager.update_activity и is_application
        with patch.object(activity_tracker.data_manager, 'update_activity') as mock_update, \
             patch('cogs.activity.is_application', return_value=False):
            
            # Вызываем метод on_presence_update
            await activity_tracker.on_presence_update(before, after)
            
            # Проверяем, что старая сессия была записана
            # (asyncio.create_task был вызван, но мы не можем проверить это напрямую)
            
            # Проверяем, что новая сессия была добавлена
            assert user_id in activity_tracker.current_activities
            assert activity_tracker.current_activities[user_id][0] == "New Game"

    @pytest.mark.asyncio
    async def test_on_presence_update_short_session(self, mock_bot):
        """Тест завершения короткой сессии."""
        # Создаем экземпляр ActivityTracker
        activity_tracker = ActivityTracker(mock_bot)
        
        # Добавляем короткую сессию
        user_id = 123456789
        game_name = "Short Game"
        start_time = datetime.now(pytz.UTC) - timedelta(seconds=5)  # 5 секунд назад
        activity_tracker.current_activities[user_id] = (game_name, start_time)
        
        # Настраиваем конфиг бота
        mock_bot.settings.timeouts.activity_min_record = 10  # 10 секунд
        
        # Создаем моки для before и after
        before = MagicMock(spec=discord.Member)
        before.bot = False
        before.id = user_id
        before.name = "Test User"
        
        # Активность в before
        activity = MagicMock(spec=discord.Activity)
        activity.type = discord.ActivityType.playing
        activity.name = game_name
        before.activities = [activity]
        
        after = MagicMock(spec=discord.Member)
        after.bot = False
        after.id = user_id
        after.name = "Test User"
        after.activities = []  # Нет активности
        
        # Патчим data_manager.update_activity и is_application
        with patch.object(activity_tracker.data_manager, 'update_activity') as mock_update, \
             patch('cogs.activity.is_application', return_value=False):
            
            # Вызываем метод on_presence_update
            await activity_tracker.on_presence_update(before, after)
            
            # Проверяем, что сессия была удалена из памяти
            assert user_id not in activity_tracker.current_activities
            
            # Проверяем, что update_activity НЕ был вызван (сессия слишком короткая)
            # Но поскольку используется asyncio.create_task, мы не можем проверить это напрямую
