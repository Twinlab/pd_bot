"""Тесты для кога AnimeCog."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.anime import AnimeCog


class TestAnimeCogInit:
    """Тесты для инициализации и выгрузки AnimeCog."""

    def test_anime_cog_init_with_channel(self, mock_bot):
        """Тест инициализации кога с настроенным каналом."""
        # Настраиваем mock_bot
        mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
        
        # Патчим tasks.loop и asyncio.create_task
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Проверяем, что атрибуты инициализированы корректно
            assert anime_cog.bot == mock_bot
            assert anime_cog.channel_id == 123456789
            
            # Проверяем, что у кога есть фоновые задачи
            assert hasattr(anime_cog, 'morning_post')
            assert hasattr(anime_cog, 'evening_post')

    def test_anime_cog_init_without_channel(self, mock_bot):
        """Тест инициализации кога без настроенного канала."""
        # Настраиваем mock_bot
        mock_bot.config = {}
        
        # Патчим tasks.loop, чтобы избежать проблем с циклом событий
        with patch('discord.ext.tasks.loop', return_value=MagicMock()):
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
        # Настраиваем mock_bot
        mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
        
        # Патчим tasks.loop и asyncio.create_task
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
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
        # Патчим tasks.loop и asyncio.create_task
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
            mock_bot.get_channel = MagicMock(return_value=mock_text_channel)
            
            # Создаем экземпляр AnimeCog
            anime_cog = AnimeCog(mock_bot)
            
            # Патчим _check_channel_exists и get_anime_image
            with patch.object(anime_cog, '_check_channel_exists', AsyncMock(return_value=True)), \
                 patch.object(anime_cog, 'get_anime_image', AsyncMock(return_value="https://example.com/anime.jpg")):
                
                # Вызываем метод post_anime_image
                result = await anime_cog.post_anime_image()
                
                # Проверяем результат
                assert result is True
                
                # Проверяем, что channel.send был вызван с правильными аргументами
                mock_text_channel.send.assert_called_once_with("https://example.com/anime.jpg")

    @pytest.mark.asyncio
    async def test_post_anime_image_no_channel(self, mock_bot):
        """Тест метода post_anime_image (канал не существует)."""
        # Патчим tasks.loop и asyncio.create_task
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
            
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
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
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
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
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
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
            
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
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
            
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
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
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
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
            
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
        with patch('discord.ext.tasks.loop', return_value=MagicMock()), \
             patch('asyncio.create_task', return_value=MagicMock()):
            # Настраиваем mock_bot
            mock_bot.config = {"ANIME_CHANNEL_ID": 123456789}
            
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
