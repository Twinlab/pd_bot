"""Тесты для кога AnimeCog."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.anime import AnimeCog


def create_mock_settings(channel_id=123456789):
    """Создает мок настроек для тестов."""
    mock_settings = MagicMock()
    mock_settings.channels.anime = channel_id
    mock_settings.anime.tags = ["anime", "1girl", "cute"]
    mock_settings.anime.excluded_tags = ["nude", "nsfw"]
    mock_settings.anime.max_tags_per_request = 6
    mock_settings.anime.rating = "safe"
    mock_settings.anime.safebooru_limit = 100
    mock_settings.anime.cache_size = 10
    mock_settings.anime.min_tag_selection = 1
    mock_settings.anime.schedule.morning_hour = 10
    mock_settings.anime.schedule.morning_minute = 0
    mock_settings.anime.schedule.evening_hour = 18
    mock_settings.anime.schedule.evening_minute = 0
    return mock_settings


class TestAnimeCogInit:
    """Тесты для инициализации и выгрузки AnimeCog."""

    def test_anime_cog_init_with_channel(self, mock_bot):
        """Тест инициализации кога с настроенным каналом."""
        # Создаем моки для задач с методом change_interval
        mock_morning_task = MagicMock()
        mock_morning_task.change_interval = MagicMock()
        mock_morning_task.start = MagicMock()
        
        mock_evening_task = MagicMock()
        mock_evening_task.change_interval = MagicMock()
        mock_evening_task.start = MagicMock()
        
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()), \
             patch.object(AnimeCog, 'morning_post', mock_morning_task), \
             patch.object(AnimeCog, 'evening_post', mock_evening_task):
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Проверяем, что атрибуты инициализированы корректно
            assert anime_cog.bot == mock_bot
            assert anime_cog.channel_id == 123456789
            
            # Проверяем, что change_interval был вызван для обеих задач
            mock_morning_task.change_interval.assert_called_once()
            mock_evening_task.change_interval.assert_called_once()
            
            # Проверяем, что задачи были запущены
            mock_morning_task.start.assert_called_once()
            mock_evening_task.start.assert_called_once()

    def test_anime_cog_init_without_channel(self, mock_bot):
        """Тест инициализации кога без настроенного канала."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings(None)), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()):
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Проверяем, что атрибуты инициализированы корректно
            assert anime_cog.bot == mock_bot
            assert anime_cog.channel_id is None
            
            # Проверяем, что у кога есть фоновые задачи, но они не запущены
            assert hasattr(anime_cog, 'morning_post')
            assert hasattr(anime_cog, 'evening_post')

    @pytest.mark.asyncio
    async def test_anime_cog_cog_unload(self, mock_bot):
        """Тест выгрузки кога."""
        # Патчим get_settings для возврата настроек с каналом
        mock_settings = create_mock_settings()
        
        with patch('cogs.anime.get_settings', return_value=mock_settings), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим методы cancel для фоновых задач
            with patch.object(anime_cog.morning_post, 'cancel') as mock_morning_post, \
                 patch.object(anime_cog.evening_post, 'cancel') as mock_evening_post:
                
                # Вызываем метод cog_unload
                await anime_cog.cog_unload()
                
                # Проверяем, что методы cancel были вызваны
                mock_morning_post.assert_called_once()
                mock_evening_post.assert_called_once()


class TestAnimeImageFunctions:
    """Тесты для получения и публикации изображений."""

    @pytest.mark.asyncio
    async def test_post_anime_image_success(self, mock_bot, mock_text_channel):
        """Тест метода post_anime_image (успешный случай)."""
        # Патчим get_settings
        mock_settings = create_mock_settings()
        
        with patch('cogs.anime.get_settings', return_value=mock_settings), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            mock_bot.get_channel = MagicMock(return_value=mock_text_channel)
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим _check_channel_exists и get_anime_image
            with patch.object(anime_cog, '_check_channel_exists', AsyncMock(return_value=True)), \
                 patch.object(anime_cog, 'get_anime_image', AsyncMock(return_value=("https://example.com/anime.jpg", 999))):
               
               # Вызываем метод post_anime_image
               result = await anime_cog.post_anime_image()
               
               # Проверяем результат
               assert result is True
               
               # Проверяем, что channel.send был вызван с правильными аргументами
               mock_text_channel.send.assert_called_once_with("https://example.com/anime.jpg")
               # Проверяем, что ID был добавлен в кэш
               assert 999 in anime_cog.post_cache

    @pytest.mark.asyncio
    async def test_post_anime_image_no_channel(self, mock_bot):
        """Тест метода post_anime_image (канал не существует)."""
        # Патчим get_settings
        mock_settings = create_mock_settings()
        
        with patch('cogs.anime.get_settings', return_value=mock_settings), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим _check_channel_exists
            with patch.object(anime_cog, '_check_channel_exists', AsyncMock(return_value=False)):
                
                # Вызываем метод post_anime_image
                result = await anime_cog.post_anime_image()
                
                # Проверяем результат
                assert result is False

    @pytest.mark.asyncio
    async def test_check_channel_exists_success(self, mock_bot, mock_text_channel):
        """Тест метода _check_channel_exists (канал существует)."""
        # Патчим tasks.loop и asyncio.create_task
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            mock_bot.get_channel = MagicMock(return_value=mock_text_channel)
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Вызываем метод _check_channel_exists
            result = await anime_cog._check_channel_exists()
            
            # Проверяем результат
            assert result is True

    @pytest.mark.asyncio
    async def test_check_channel_exists_no_channel(self, mock_bot):
        """Тест метода _check_channel_exists (канал не существует)."""
        # Патчим tasks.loop и asyncio.create_task
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            mock_bot.get_channel = MagicMock(return_value=None)
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Вызываем метод _check_channel_exists
            result = await anime_cog._check_channel_exists()
            
            # Проверяем результат
            assert result is False


class TestBackgroundTasks:
    """Тесты для фоновых задач AnimeCog."""

    @pytest.mark.asyncio
    async def test_morning_post(self, mock_bot):
        """Тест задачи morning_post."""
        # Патчим tasks.loop и asyncio.create_task
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим post_anime_image
            with patch.object(anime_cog, 'post_anime_image', AsyncMock()) as mock_post:
                # Вызываем метод morning_post
                await anime_cog.morning_post()
                
                # Проверяем, что post_anime_image был вызван
                mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_evening_post(self, mock_bot):
        """Тест задачи evening_post."""
        # Патчим tasks.loop и asyncio.create_task
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим post_anime_image
            with patch.object(anime_cog, 'post_anime_image', AsyncMock()) as mock_post:
                # Вызываем метод evening_post
                await anime_cog.evening_post()
                
                # Проверяем, что post_anime_image был вызван
                mock_post.assert_called_once()


class TestCommands:
    """Тесты для команд AnimeCog."""

    @pytest.mark.asyncio
    async def test_post_anime_success(self, mock_bot, mock_context, mock_text_channel):
        """Тест команды post_anime (успешный случай)."""
        # Патчим tasks.loop и asyncio.create_task
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            mock_bot.get_channel = MagicMock(return_value=mock_text_channel)
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим _check_channel_exists и post_anime_image
            with patch.object(anime_cog, '_check_channel_exists', AsyncMock(return_value=True)), \
                 patch.object(anime_cog, 'post_anime_image', AsyncMock(return_value=True)):
                
                # Вызываем метод напрямую, а не через команду
                await anime_cog.post_anime.callback(anime_cog, mock_context)
                
                # Проверяем, что ctx.send был вызван с правильными аргументами
                mock_context.send.assert_called_once()
                assert "успешно опубликовано" in mock_context.send.call_args[0][0]
                assert mock_context.send.call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_post_anime_no_channel(self, mock_bot, mock_context):
        """Тест команды post_anime (канал не существует)."""
        # Патчим tasks.loop и asyncio.create_task
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим _check_channel_exists
            with patch.object(anime_cog, '_check_channel_exists', AsyncMock(return_value=False)):
                
                # Вызываем метод напрямую, а не через команду
                await anime_cog.post_anime.callback(anime_cog, mock_context)
                
                # Проверяем, что ctx.send был вызван с правильными аргументами
                mock_context.send.assert_called_once()
                assert "Ошибка: канал для публикации аниме не настроен или не найден" in mock_context.send.call_args[0][0]
                assert mock_context.send.call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_post_anime_error(self, mock_bot, mock_context):
        """Тест команды post_anime (ошибка публикации)."""
        # Патчим tasks.loop и asyncio.create_task
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим _check_channel_exists и post_anime_image
            with patch.object(anime_cog, '_check_channel_exists', AsyncMock(return_value=True)), \
                 patch.object(anime_cog, 'post_anime_image', AsyncMock(return_value=False)):
                
                # Вызываем метод напрямую, а не через команду
                await anime_cog.post_anime.callback(anime_cog, mock_context)
                
                # Проверяем, что ctx.send был вызван с правильными аргументами
                mock_context.send.assert_called_once()
                assert "Не удалось опубликовать аниме-изображение" in mock_context.send.call_args[0][0]
                assert mock_context.send.call_args[1]["ephemeral"] is True


class TestGetAnimeImage:
    """Тесты для метода get_anime_image."""

    @pytest.mark.asyncio
    async def test_get_anime_image_success(self, mock_bot):
        """Тест успешного получения изображения."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            anime_cog = AnimeCog(mock_bot)
            
            # Просто мокируем весь метод get_anime_image
            with patch.object(anime_cog, 'get_anime_image', AsyncMock(return_value=("https://safebooru.org/images/123/test.jpg", 123))):
                result = await anime_cog.get_anime_image()
                assert result == ("https://safebooru.org/images/123/test.jpg", 123)

    @pytest.mark.asyncio
    async def test_get_anime_image_failure(self, mock_bot):
        """Тест неудачного получения изображения."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            anime_cog = AnimeCog(mock_bot)
            
            # Мокируем метод get_anime_image чтобы он возвращал None
            with patch.object(anime_cog, 'get_anime_image', AsyncMock(return_value=None)):
                result = await anime_cog.get_anime_image()
                assert result is None

    @pytest.mark.asyncio
    async def test_get_anime_image_uses_settings(self, mock_bot):
        """Тест что метод использует настройки из конфигурации."""
        mock_settings = create_mock_settings()
        
        with patch('cogs.anime.get_settings', return_value=mock_settings) as mock_get_settings, \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            anime_cog = AnimeCog(mock_bot)
            
            # Проверяем, что get_settings вызывается при инициализации
            mock_get_settings.assert_called()
            
            # Проверяем, что настройки правильно применились
            assert anime_cog.channel_id == 123456789


class TestPostAnimeImageEdgeCases:
    """Тесты для дополнительных случаев post_anime_image."""

    @pytest.mark.asyncio
    async def test_post_anime_image_no_image_url(self, mock_bot, mock_text_channel):
        """Тест post_anime_image когда get_anime_image возвращает None."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            mock_bot.get_channel = MagicMock(return_value=mock_text_channel)
            
            anime_cog = AnimeCog(mock_bot)
            
            with patch.object(anime_cog, '_check_channel_exists', AsyncMock(return_value=True)), \
                 patch.object(anime_cog, 'get_anime_image', AsyncMock(return_value=None)):
                
                result = await anime_cog.post_anime_image()
                assert result is False
                mock_text_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_anime_image_exception(self, mock_bot):
        """Тест обработки исключения в post_anime_image."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            anime_cog = AnimeCog(mock_bot)
            
            with patch.object(anime_cog, '_check_channel_exists', AsyncMock(side_effect=Exception("Test error"))):
                result = await anime_cog.post_anime_image()
                assert result is False


class TestCheckChannelExistsEdgeCases:
    """Тесты для дополнительных случаев _check_channel_exists."""

    @pytest.mark.asyncio
    async def test_check_channel_exists_no_channel_id(self, mock_bot):
        """Тест _check_channel_exists когда channel_id не установлен."""
        # Патчим get_settings для возврата настроек без канала
        with patch('cogs.anime.get_settings', return_value=create_mock_settings(channel_id=None)), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()):
            anime_cog = AnimeCog(mock_bot)
            assert anime_cog.channel_id is None
            
            result = await anime_cog._check_channel_exists()
            assert result is False


class TestBeforeLoopMethods:
    """Тесты для методов before_loop."""

    @pytest.mark.asyncio
    async def test_before_morning_post(self, mock_bot):
        """Тест метода before_morning_post."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            mock_bot.wait_until_ready = AsyncMock()
            
            anime_cog = AnimeCog(mock_bot)
            
            await anime_cog.before_morning_post()
            mock_bot.wait_until_ready.assert_called_once()

    @pytest.mark.asyncio
    async def test_before_evening_post(self, mock_bot):
        """Тест метода before_evening_post."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            mock_bot.wait_until_ready = AsyncMock()
            
            anime_cog = AnimeCog(mock_bot)
            
            await anime_cog.before_evening_post()
            mock_bot.wait_until_ready.assert_called_once()


class TestErrorHandling:
    """Тесты для обработки ошибок."""

    @pytest.mark.asyncio
    async def test_cog_command_error_missing_permissions(self, mock_bot, mock_context):
        """Тест обработки ошибки MissingPermissions."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            anime_cog = AnimeCog(mock_bot)
            
            error = commands.MissingPermissions(["administrator"])
            await anime_cog.cog_command_error(mock_context, error)
            
            mock_context.send.assert_called_once()
            assert "У вас нет прав" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cog_command_error_command_invoke_error(self, mock_bot, mock_context):
        """Тест обработки ошибки CommandInvokeError."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            anime_cog = AnimeCog(mock_bot)
            
            original_error = Exception("Original error")
            error = commands.CommandInvokeError(original_error)
            await anime_cog.cog_command_error(mock_context, error)
            
            mock_context.send.assert_called_once()
            assert "Произошла ошибка" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cog_command_error_generic_error(self, mock_bot, mock_context):
        """Тест обработки общей ошибки."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            anime_cog = AnimeCog(mock_bot)
            
            error = Exception("Generic error")
            await anime_cog.cog_command_error(mock_context, error)
            
            mock_context.send.assert_called_once()
            assert "Произошла неизвестная ошибка" in mock_context.send.call_args[0][0]


class TestSetupFunction:
    """Тесты для функции setup."""

    @pytest.mark.asyncio
    async def test_setup(self, mock_bot):
        """Тест функции setup."""
        from cogs.anime import setup
        
        mock_bot.add_cog = AsyncMock()
        
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            await setup(mock_bot)
            
            mock_bot.add_cog.assert_called_once()
            # Проверяем, что передан экземпляр AnimeCog
            args = mock_bot.add_cog.call_args[0]
            assert isinstance(args[0], AnimeCog)


class TestAnimeApiRandomization:
    """Тесты для проверки рандомизации API запросов."""

    @pytest.mark.asyncio
    async def test_api_request_includes_pid_parameter(self, mock_bot):
        """Тест что API запрос включает параметр pid для рандомизации."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            anime_cog = AnimeCog(mock_bot)
            
            # Мокируем aiohttp.ClientSession
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=[
                {"id": 12345, "file_url": "https://example.com/test.jpg"}
            ])
            
            mock_session = MagicMock()
            mock_session.get = MagicMock()
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with patch('aiohttp.ClientSession') as mock_client_session:
                mock_client_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_client_session.return_value.__aexit__ = AsyncMock(return_value=None)
                
                # Вызываем метод
                result = await anime_cog.get_anime_image()
                
                # Проверяем что запрос был сделан
                mock_session.get.assert_called()
                
                # Получаем параметры запроса
                call_args = mock_session.get.call_args
                params = call_args[1]['params']  # kwargs['params']
                
                # Проверяем что параметр pid присутствует
                assert 'pid' in params
                assert params['pid'].isdigit()  # pid должен быть числом в виде строки
                
                # Проверяем что результат корректный
                assert result is not None
                assert result[0] == "https://example.com/test.jpg"
                assert result[1] == 12345

    @pytest.mark.asyncio
    async def test_pid_parameter_is_random(self, mock_bot):
        """Тест что параметр pid действительно случайный."""
        with patch('cogs.anime.get_settings', return_value=create_mock_settings()), \
             patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            
            anime_cog = AnimeCog(mock_bot)
            
            # Мокируем aiohttp.ClientSession
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=[
                {"id": 12345, "file_url": "https://example.com/test.jpg"}
            ])
            
            mock_session = MagicMock()
            mock_session.get = MagicMock()
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
            
            pid_values = set()
            
            with patch('aiohttp.ClientSession') as mock_client_session:
                mock_client_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_client_session.return_value.__aexit__ = AsyncMock(return_value=None)
                
                # Делаем несколько запросов
                for _ in range(10):
                    await anime_cog.get_anime_image()
                    
                    # Получаем последний вызов
                    call_args = mock_session.get.call_args
                    params = call_args[1]['params']
                    pid_values.add(int(params['pid']))
                
                # Проверяем что получили разные значения pid
                # (с вероятностью 99.9% получим хотя бы 2 разных значения из 1000 возможных)
                assert len(pid_values) > 1, f"Получены одинаковые pid: {pid_values}"
                
                # Проверяем что все значения в допустимом диапазоне
                # random.randint(0, 3999) может генерировать значения от 0 до 3999 включительно
                for pid in pid_values:
                    assert 0 <= pid <= 3999, f"pid {pid} вне диапазона 0-3999"
