"""Тесты для команды quotes в коге fun.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.fun import FunCog


class TestQuoteCommand:
    """Тесты для команды quote."""

    @pytest.fixture
    def fun_cog(self):
        """Создает экземпляр FunCog для тестирования."""
        mock_bot = MagicMock()
        return FunCog(mock_bot)

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    @patch("cogs.fun.get_settings")
    async def test_quotes_command_no_folder_no_folders_available(self, mock_settings, mock_scan, fun_cog):
        """Тест команды quotes без параметра, когда нет доступных папок."""
        # Настройка моков
        mock_scan.return_value = []
        mock_settings_obj = MagicMock()
        mock_settings_obj.colors.error = "#ff0000"
        mock_settings.return_value = mock_settings_obj
        
        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456
        
        await fun_cog.quote.callback(fun_cog, mock_ctx, None)
        
        # Проверяем, что отправлено сообщение об ошибке
        mock_ctx.send.assert_called_once()
        call_args = mock_ctx.send.call_args
        assert call_args.kwargs.get("ephemeral") is True
        assert "embed" in call_args.kwargs

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    @patch("cogs.fun.get_settings")
    @patch("cogs.fun.QuotesSelectView")
    async def test_quotes_command_no_folder_with_folders_available(
        self, mock_view_class, mock_settings, mock_scan, fun_cog
    ):
        """Тест команды quotes без параметра, когда есть доступные папки."""
        # Настройка моков
        mock_scan.return_value = ["folder1", "folder2"]
        mock_settings_obj = MagicMock()
        mock_settings_obj.colors.default = "#0099ff"
        mock_settings.return_value = mock_settings_obj
        mock_view = MagicMock()
        mock_view_class.return_value = mock_view
        
        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.interaction = MagicMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456
        
        await fun_cog.quote.callback(fun_cog, mock_ctx, None)
        
        # Проверяем, что создан View и отправлено сообщение
        mock_view_class.assert_called_once()
        mock_ctx.send.assert_called_once()
        call_args = mock_ctx.send.call_args
        assert "embed" in call_args.kwargs
        assert "view" in call_args.kwargs
        assert call_args.kwargs.get("ephemeral") is False

    @pytest.mark.asyncio
    @patch("cogs.fun.validate_folder_exists")
    @patch("cogs.fun.send_random_quote_image")
    async def test_quotes_command_with_valid_folder(self, mock_send, mock_validate, fun_cog):
        """Тест команды quotes с валидным именем папки."""
        # Настройка моков
        mock_validate.return_value = True
        mock_send.return_value = None
        
        mock_ctx = MagicMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456
        
        await fun_cog.quote.callback(fun_cog, mock_ctx, "test_folder")
        
        # Проверяем, что функция отправки была вызвана
        mock_validate.assert_called_once_with("test_folder")
        mock_send.assert_called_once_with(mock_ctx, "test_folder")

    @pytest.mark.asyncio
    @patch("cogs.fun.validate_folder_exists")
    @patch("cogs.fun.scan_quotes_folders")
    @patch("cogs.fun.get_settings")
    async def test_quotes_command_with_invalid_folder(self, mock_settings, mock_scan, mock_validate, fun_cog):
        """Тест команды quotes с невалидным именем папки."""
        # Настройка моков
        mock_validate.return_value = False
        mock_scan.return_value = ["folder1", "folder2"]
        mock_settings_obj = MagicMock()
        mock_settings_obj.colors.error = "#ff0000"
        mock_settings.return_value = mock_settings_obj
        
        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456
        
        await fun_cog.quote.callback(fun_cog, mock_ctx, "invalid_folder")
        
        # Проверяем, что отправлено сообщение об ошибке
        mock_ctx.send.assert_called_once()
        call_args = mock_ctx.send.call_args
        assert call_args.kwargs.get("ephemeral") is True
        assert "embed" in call_args.kwargs

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quotes_autocomplete_no_input(self, mock_scan, fun_cog):
        """Тест автокомплита без ввода пользователя."""
        mock_scan.return_value = ["folder1", "folder2", "folder3"]
        
        mock_interaction = MagicMock()
        
        result = await fun_cog.quote_autocomplete(mock_interaction, "")
        
        assert len(result) == 3
        assert all(choice.name in ["folder1", "folder2", "folder3"] for choice in result)
        assert all(choice.value in ["folder1", "folder2", "folder3"] for choice in result)

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quotes_autocomplete_with_filter(self, mock_scan, fun_cog):
        """Тест автокомплита с фильтрацией по вводу."""
        mock_scan.return_value = ["folder1", "test_folder", "another"]
        
        mock_interaction = MagicMock()
        
        result = await fun_cog.quote_autocomplete(mock_interaction, "fold")
        
        # Должны вернуться только папки, содержащие "fold"
        assert len(result) == 2
        folder_names = [choice.name for choice in result]
        assert "folder1" in folder_names
        assert "test_folder" in folder_names
        assert "another" not in folder_names

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quotes_autocomplete_limit_25(self, mock_scan, fun_cog):
        """Тест ограничения автокомплита до 25 вариантов."""
        # Создаем 30 папок
        folders = [f"folder{i}" for i in range(30)]
        mock_scan.return_value = folders
        
        mock_interaction = MagicMock()
        
        result = await fun_cog.quote_autocomplete(mock_interaction, "")
        
        # Должно вернуться максимум 25 вариантов
        assert len(result) <= 25

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quotes_autocomplete_error_handling(self, mock_scan, fun_cog):
        """Тест обработки ошибок в автокомплите."""
        mock_scan.side_effect = Exception("Test error")
        
        mock_interaction = MagicMock()
        
        result = await fun_cog.quote_autocomplete(mock_interaction, "test")
        
        # При ошибке должен вернуться пустой список
        assert result == []

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    async def test_quotes_autocomplete_case_insensitive(self, mock_scan, fun_cog):
        """Тест регистронезависимой фильтрации в автокомплите."""
        mock_scan.return_value = ["TestFolder", "UPPERCASE", "lowercase"]
        
        mock_interaction = MagicMock()
        
        # Тестируем поиск в нижнем регистре
        result = await fun_cog.quote_autocomplete(mock_interaction, "test")
        
        assert len(result) == 1
        assert result[0].name == "TestFolder"
        
        # Тестируем поиск в верхнем регистре
        result = await fun_cog.quote_autocomplete(mock_interaction, "UPPER")
        
        assert len(result) == 1
        assert result[0].name == "UPPERCASE"


class TestQuotesCommandIntegration:
    """Интеграционные тесты для команды quotes."""

    @pytest.fixture
    def fun_cog(self):
        """Создает экземпляр FunCog для тестирования."""
        mock_bot = MagicMock()
        return FunCog(mock_bot)

    @pytest.mark.asyncio
    @patch("cogs.fun.validate_folder_exists")
    @patch("cogs.fun.send_random_quote_image")
    @patch("cogs.fun.scan_quotes_folders")
    @patch("cogs.fun.get_settings")
    async def test_quotes_command_full_flow_with_folder(
        self, mock_settings, mock_scan, mock_send, mock_validate, fun_cog
    ):
        """Тест полного потока команды quotes с указанием папки."""
        # Настройка моков для успешного выполнения
        mock_validate.return_value = True
        mock_send.return_value = None
        
        mock_ctx = MagicMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456
        
        await fun_cog.quote.callback(fun_cog, mock_ctx, "test_folder")
        
        # Проверяем последовательность вызовов
        mock_validate.assert_called_once_with("test_folder")
        mock_send.assert_called_once_with(mock_ctx, "test_folder")
        
        # scan_quotes_folders не должен вызываться при указании папки
        mock_scan.assert_not_called()

    @pytest.mark.asyncio
    @patch("cogs.fun.scan_quotes_folders")
    @patch("cogs.fun.get_settings")
    @patch("cogs.fun.QuotesSelectView")
    async def test_quotes_command_full_flow_without_folder(
        self, mock_view_class, mock_settings, mock_scan, fun_cog
    ):
        """Тест полного потока команды quotes без указания папки."""
        # Настройка моков
        mock_scan.return_value = ["folder1", "folder2"]
        mock_settings_obj = MagicMock()
        mock_settings_obj.colors.default = "#0099ff"
        mock_settings.return_value = mock_settings_obj
        mock_view = MagicMock()
        mock_view_class.return_value = mock_view
        
        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.interaction = MagicMock()
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "quote"
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.guild = None
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456
        
        await fun_cog.quote.callback(fun_cog, mock_ctx, None)
        
        # Проверяем последовательность вызовов
        mock_scan.assert_called_once()
        mock_view_class.assert_called_once()
        mock_ctx.send.assert_called_once()
        
        # Проверяем параметры отправленного сообщения
        call_args = mock_ctx.send.call_args
        assert "embed" in call_args.kwargs
        assert "view" in call_args.kwargs
        assert call_args.kwargs["view"] == mock_view
