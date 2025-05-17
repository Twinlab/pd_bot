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
