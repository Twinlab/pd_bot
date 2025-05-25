"""Тесты для модуля snipe_utils."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils import snipe_utils
from utils.snipe_utils import save_deleted_message, show_sniped_message


class TestSnipeCache:
    """Тесты для работы с кэшем snipe."""

    def test_snipe_cache_exists(self):
        """Тест наличия глобального кэша."""
        assert hasattr(snipe_utils, 'snipe_cache')
        assert isinstance(snipe_utils.snipe_cache, dict)

    def test_snipe_cache_manipulation(self):
        """Тест прямого манипулирования кэшем."""
        # Очищаем кэш
        snipe_utils.snipe_cache.clear()
        
        # Добавляем тестовые данные
        test_data = {
            "content": "Test message",
            "author_name": "Test User",
            "timestamp": datetime.now()
        }
        snipe_utils.snipe_cache["123"] = test_data
        
        # Проверяем что данные сохранились
        assert "123" in snipe_utils.snipe_cache
        assert snipe_utils.snipe_cache["123"]["content"] == "Test message"
        
        # Очищаем после теста
        snipe_utils.snipe_cache.clear()


class TestSaveDeletedMessage:
    """Тесты для функции save_deleted_message."""

    def setup_method(self):
        """Очищаем кэш перед каждым тестом."""
        snipe_utils.snipe_cache.clear()

    def teardown_method(self):
        """Очищаем кэш после каждого теста."""
        snipe_utils.snipe_cache.clear()

    @pytest.mark.asyncio
    async def test_save_deleted_message_with_content(self):
        """Тест сохранения сообщения с текстом."""
        # Создаем мок сообщения
        mock_message = MagicMock(spec=discord.Message)
        mock_message.author.bot = False
        mock_message.content = "Test message content"
        mock_message.attachments = []
        mock_message.channel.id = 123456
        mock_message.author.display_name = "Test User"
        mock_message.author.avatar = MagicMock()
        mock_message.author.avatar.url = "https://example.com/avatar.png"
        mock_message.created_at = datetime(2023, 1, 1, 12, 0, 0)

        await save_deleted_message(mock_message)

        # Проверяем что сообщение сохранилось
        assert "123456" in snipe_utils.snipe_cache
        saved_data = snipe_utils.snipe_cache["123456"]
        assert saved_data["content"] == "Test message content"
        assert saved_data["author_name"] == "Test User"
        assert saved_data["author_avatar"] == "https://example.com/avatar.png"
        assert saved_data["timestamp"] == datetime(2023, 1, 1, 12, 0, 0)
        assert saved_data["has_attachments"] is False
        assert saved_data["attachments"] == []

    @pytest.mark.asyncio
    async def test_save_deleted_message_with_attachments(self):
        """Тест сохранения сообщения с вложениями."""
        # Создаем мок вложения
        mock_attachment = MagicMock(spec=discord.Attachment)
        mock_attachment.url = "https://example.com/image.png"
        mock_attachment.filename = "image.png"
        mock_attachment.content_type = "image/png"
        mock_attachment.size = 1024
        mock_attachment.width = 800
        mock_attachment.height = 600

        # Создаем мок сообщения
        mock_message = MagicMock(spec=discord.Message)
        mock_message.author.bot = False
        mock_message.content = "Check this image!"
        mock_message.attachments = [mock_attachment]
        mock_message.channel.id = 123456
        mock_message.author.display_name = "Test User"
        mock_message.author.avatar = None
        mock_message.author.default_avatar = MagicMock()
        mock_message.author.default_avatar.url = "https://example.com/default.png"
        mock_message.created_at = datetime(2023, 1, 1, 12, 0, 0)

        await save_deleted_message(mock_message)

        # Проверяем что сообщение сохранилось
        assert "123456" in snipe_utils.snipe_cache
        saved_data = snipe_utils.snipe_cache["123456"]
        assert saved_data["content"] == "Check this image!"
        assert saved_data["author_avatar"] == "https://example.com/default.png"
        assert saved_data["has_attachments"] is True
        assert len(saved_data["attachments"]) == 1
        
        attachment_data = saved_data["attachments"][0]
        assert attachment_data["url"] == "https://example.com/image.png"
        assert attachment_data["filename"] == "image.png"
        assert attachment_data["content_type"] == "image/png"
        assert attachment_data["size"] == 1024
        assert attachment_data["width"] == 800
        assert attachment_data["height"] == 600
        assert attachment_data["is_image"] is True

    @pytest.mark.asyncio
    async def test_save_deleted_message_bot_ignored(self):
        """Тест игнорирования сообщений от ботов."""
        mock_message = MagicMock(spec=discord.Message)
        mock_message.author.bot = True
        mock_message.content = "Bot message"
        mock_message.channel.id = 123456

        await save_deleted_message(mock_message)

        # Проверяем что сообщение НЕ сохранилось
        assert "123456" not in snipe_utils.snipe_cache

    @pytest.mark.asyncio
    async def test_save_deleted_message_empty_ignored(self):
        """Тест игнорирования пустых сообщений."""
        mock_message = MagicMock(spec=discord.Message)
        mock_message.author.bot = False
        mock_message.content = ""
        mock_message.attachments = []
        mock_message.channel.id = 123456

        await save_deleted_message(mock_message)

        # Проверяем что сообщение НЕ сохранилось
        assert "123456" not in snipe_utils.snipe_cache

    @pytest.mark.asyncio
    async def test_save_deleted_message_error_handling(self):
        """Тест обработки ошибок при сохранении."""
        # Создаем сообщение которое вызовет ошибку при доступе к channel.id
        mock_message = MagicMock(spec=discord.Message)
        mock_message.author.bot = False
        mock_message.content = "Test message"
        mock_message.attachments = []
        
        # Настраиваем channel так чтобы доступ к id вызвал ошибку
        mock_channel = MagicMock()
        type(mock_channel).id = property(lambda self: 1/0)
        mock_message.channel = mock_channel

        with patch('utils.snipe_utils.logger') as mock_logger:
            await save_deleted_message(mock_message)
            
            # Проверяем что ошибка была залогирована
            mock_logger.error.assert_called_once()
            assert "Ошибка при сохранении удаленного сообщения" in mock_logger.error.call_args[0][0]


class TestShowSnipedMessage:
    """Тесты для функции show_sniped_message."""

    def setup_method(self):
        """Очищаем кэш перед каждым тестом."""
        snipe_utils.snipe_cache.clear()

    def teardown_method(self):
        """Очищаем кэш после каждого теста."""
        snipe_utils.snipe_cache.clear()

    @pytest.mark.asyncio
    async def test_show_sniped_message_no_cache(self):
        """Тест отображения когда нет сохраненных сообщений."""
        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()

        await show_sniped_message(mock_ctx)

        mock_ctx.send.assert_called_once_with("Нет удаленных сообщений для восстановления.")

    @pytest.mark.asyncio
    async def test_show_sniped_message_with_content_only(self):
        """Тест отображения сообщения только с текстом."""
        # Подготавливаем данные в кэше
        snipe_utils.snipe_cache["123456"] = {
            "content": "Test message content",
            "author_name": "Test User",
            "author_avatar": "https://example.com/avatar.png",
            "timestamp": datetime(2023, 1, 1, 12, 0, 0),
            "has_attachments": False,
            "attachments": []
        }

        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()

        await show_sniped_message(mock_ctx)

        # Проверяем что send был вызван с эмбедом
        mock_ctx.send.assert_called_once()
        call_args = mock_ctx.send.call_args
        assert 'embed' in call_args.kwargs
        
        embed = call_args.kwargs['embed']
        assert embed.description == "Test message content"
        assert embed.author.name == "Test User"
        assert embed.author.icon_url == "https://example.com/avatar.png"
        assert embed.color == discord.Color.red()
        assert embed.footer.text == "Сообщение было удалено"

    @pytest.mark.asyncio
    async def test_show_sniped_message_with_image_attachment(self):
        """Тест отображения сообщения с изображением."""
        snipe_utils.snipe_cache["123456"] = {
            "content": "Check this image!",
            "author_name": "Test User",
            "author_avatar": "https://example.com/avatar.png",
            "timestamp": datetime(2023, 1, 1, 12, 0, 0),
            "has_attachments": True,
            "attachments": [
                {
                    "url": "https://example.com/image.png",
                    "filename": "image.png",
                    "content_type": "image/png",
                    "size": 1024,
                    "is_image": True
                }
            ]
        }

        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()

        await show_sniped_message(mock_ctx)

        call_args = mock_ctx.send.call_args
        embed = call_args.kwargs['embed']
        
        # Проверяем что изображение установлено
        assert embed.image.url == "https://example.com/image.png"
        
        # Проверяем поле с вложениями
        assert len(embed.fields) == 1
        assert embed.fields[0].name == "Вложения"
        assert "image.png" in embed.fields[0].value
        assert "(image/png)" in embed.fields[0].value
        assert "1.0 KB" in embed.fields[0].value

    @pytest.mark.asyncio
    async def test_show_sniped_message_image_only(self):
        """Тест отображения сообщения только с изображением (без текста)."""
        snipe_utils.snipe_cache["123456"] = {
            "content": "",
            "author_name": "Test User",
            "author_avatar": "https://example.com/avatar.png",
            "timestamp": datetime(2023, 1, 1, 12, 0, 0),
            "has_attachments": True,
            "attachments": [
                {
                    "url": "https://example.com/image.png",
                    "filename": "image.png",
                    "content_type": "image/png",
                    "size": 1024,
                    "is_image": True
                }
            ]
        }

        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()

        await show_sniped_message(mock_ctx)

        call_args = mock_ctx.send.call_args
        embed = call_args.kwargs['embed']
        
        # Проверяем что добавлено описание для изображения без текста
        assert embed.description == "*Сообщение содержало только изображение*"

    @pytest.mark.asyncio
    async def test_show_sniped_message_error_handling(self):
        """Тест обработки ошибок при отображении."""
        # Подготавливаем данные в кэше
        snipe_utils.snipe_cache["123456"] = {
            "content": "Test message",
            "author_name": "Test User",
            "author_avatar": "https://example.com/avatar.png",
            "timestamp": datetime(2023, 1, 1, 12, 0, 0),
            "has_attachments": False,
            "attachments": []
        }

        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        # Делаем так чтобы send вызвал ошибку
        mock_ctx.send = AsyncMock(side_effect=Exception("Discord API error"))

        with patch('utils.snipe_utils.logger') as mock_logger:
            # Настраиваем send так чтобы первый вызов упал, а второй прошел
            mock_ctx.send = AsyncMock(side_effect=[Exception("Discord API error"), None])
            
            await show_sniped_message(mock_ctx)
            
            # Проверяем что ошибка была залогирована
            mock_logger.error.assert_called_once()
            assert "Ошибка при отображении удаленного сообщения" in mock_logger.error.call_args[0][0]
            
            # Проверяем что было два вызова send (второй с сообщением об ошибке)
            assert mock_ctx.send.call_count == 2
            error_call = mock_ctx.send.call_args_list[1]
            assert "Произошла ошибка при отображении удаленного сообщения" in error_call[0][0]


class TestSnipeUtilsIntegration:
    """Интеграционные тесты для snipe_utils."""

    def setup_method(self):
        """Очищаем кэш перед каждым тестом."""
        snipe_utils.snipe_cache.clear()

    def teardown_method(self):
        """Очищаем кэш после каждого теста."""
        snipe_utils.snipe_cache.clear()

    @pytest.mark.asyncio
    async def test_full_snipe_workflow(self):
        """Тест полного workflow: сохранение и отображение."""
        # Создаем и сохраняем сообщение
        mock_message = MagicMock(spec=discord.Message)
        mock_message.author.bot = False
        mock_message.content = "This will be deleted!"
        mock_message.attachments = []
        mock_message.channel.id = 123456
        mock_message.author.display_name = "Test User"
        mock_message.author.avatar = MagicMock()
        mock_message.author.avatar.url = "https://example.com/avatar.png"
        mock_message.created_at = datetime(2023, 1, 1, 12, 0, 0)

        await save_deleted_message(mock_message)

        # Теперь показываем сохраненное сообщение
        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()

        await show_sniped_message(mock_ctx)

        # Проверяем что сообщение было отображено корректно
        mock_ctx.send.assert_called_once()
        call_args = mock_ctx.send.call_args
        embed = call_args.kwargs['embed']
        assert embed.description == "This will be deleted!"
        assert embed.author.name == "Test User"
