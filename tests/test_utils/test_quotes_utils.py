"""Тесты для модуля quotes_utils.py."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.quotes_utils import (
    FolderNotFoundError,
    NoImagesFoundError,
    get_folder_stats,
    get_images_from_folder,
    get_quotes_path,
    get_random_image_from_folder,
    get_supported_extensions,
    scan_quotes_folders,
    send_random_quote_image,
    validate_folder_exists,
)


class TestQuotesUtilsBasic:
    """Тесты для базовых функций quotes_utils."""

    @patch("utils.quotes_utils.get_settings")
    def test_get_quotes_path(self, mock_get_settings):
        """Тест получения пути к папке quotes."""
        mock_settings = MagicMock()
        mock_settings.fun.quotes.assets_path = "test/quotes"
        mock_get_settings.return_value = mock_settings
        
        result = get_quotes_path()
        
        assert isinstance(result, Path)
        assert str(result) == "test/quotes"

    @patch("utils.quotes_utils.get_settings")
    def test_get_supported_extensions(self, mock_get_settings):
        """Тест получения поддерживаемых расширений."""
        mock_settings = MagicMock()
        mock_settings.fun.quotes.supported_extensions = [".jpg", ".png", ".gif"]
        mock_get_settings.return_value = mock_settings
        
        result = get_supported_extensions()
        
        assert result == [".jpg", ".png", ".gif"]


class TestScanQuotesFolders:
    """Тесты для функции scan_quotes_folders."""

    @patch("utils.quotes_utils.get_quotes_path")
    @patch("utils.quotes_utils.get_supported_extensions")
    def test_scan_quotes_folders_success(self, mock_extensions, mock_path):
        """Тест успешного сканирования папок."""
        mock_extensions.return_value = [".jpg", ".png"]
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_path.return_value = temp_path
            
            # Создаем тестовые папки и файлы
            folder1 = temp_path / "folder1"
            folder1.mkdir()
            (folder1 / "image1.jpg").touch()
            
            folder2 = temp_path / "folder2"
            folder2.mkdir()
            (folder2 / "image2.png").touch()
            
            # Папка без изображений
            folder3 = temp_path / "empty"
            folder3.mkdir()
            (folder3 / "text.txt").touch()
            
            result = scan_quotes_folders()
            
            assert "folder1" in result
            assert "folder2" in result
            assert "empty" not in result
            assert len(result) == 2

    @patch("utils.quotes_utils.get_quotes_path")
    def test_scan_quotes_folders_no_directory(self, mock_path):
        """Тест сканирования несуществующей папки."""
        mock_path.return_value = Path("/nonexistent/path")
        
        result = scan_quotes_folders()
        
        assert result == []

    @patch("utils.quotes_utils.get_quotes_path")
    @patch("utils.quotes_utils.get_supported_extensions")
    def test_scan_quotes_folders_error(self, mock_extensions, mock_path):
        """Тест обработки ошибки при сканировании."""
        mock_extensions.return_value = [".jpg"]
        mock_path.return_value.exists.return_value = True
        mock_path.return_value.iterdir.side_effect = PermissionError("Access denied")
        
        result = scan_quotes_folders()
        
        assert result == []


class TestValidateFolderExists:
    """Тесты для функции validate_folder_exists."""

    def test_validate_folder_exists_empty_name(self):
        """Тест валидации пустого имени папки."""
        assert validate_folder_exists("") is False
        assert validate_folder_exists(None) is False

    @patch("utils.quotes_utils.get_quotes_path")
    @patch("utils.quotes_utils.get_supported_extensions")
    def test_validate_folder_exists_success(self, mock_extensions, mock_path):
        """Тест успешной валидации папки."""
        mock_extensions.return_value = [".jpg"]
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_path.return_value = temp_path
            
            # Создаем тестовую папку с изображением
            folder = temp_path / "test_folder"
            folder.mkdir()
            (folder / "image.jpg").touch()
            
            result = validate_folder_exists("test_folder")
            
            assert result is True

    @patch("utils.quotes_utils.get_quotes_path")
    def test_validate_folder_exists_not_found(self, mock_path):
        """Тест валидации несуществующей папки."""
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_path.return_value = Path(temp_dir)
            
            result = validate_folder_exists("nonexistent")
            
            assert result is False


class TestGetImagesFromFolder:
    """Тесты для функции get_images_from_folder."""

    @patch("utils.quotes_utils.validate_folder_exists")
    def test_get_images_from_folder_not_found(self, mock_validate):
        """Тест получения изображений из несуществующей папки."""
        mock_validate.return_value = False
        
        with pytest.raises(FolderNotFoundError):
            get_images_from_folder("nonexistent")

    @patch("utils.quotes_utils.validate_folder_exists")
    @patch("utils.quotes_utils.get_quotes_path")
    @patch("utils.quotes_utils.get_supported_extensions")
    def test_get_images_from_folder_success(self, mock_extensions, mock_path, mock_validate):
        """Тест успешного получения изображений."""
        mock_validate.return_value = True
        mock_extensions.return_value = [".jpg", ".png"]
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_path.return_value = temp_path
            
            # Создаем тестовую папку с изображениями
            folder = temp_path / "test_folder"
            folder.mkdir()
            image1 = folder / "image1.jpg"
            image2 = folder / "image2.png"
            text_file = folder / "text.txt"
            
            image1.touch()
            image2.touch()
            text_file.touch()
            
            result = get_images_from_folder("test_folder")
            
            assert len(result) == 2
            assert image1 in result
            assert image2 in result
            assert text_file not in result


class TestGetRandomImageFromFolder:
    """Тесты для функции get_random_image_from_folder."""

    @patch("utils.quotes_utils.get_images_from_folder")
    def test_get_random_image_from_folder_success(self, mock_get_images):
        """Тест получения случайного изображения."""
        mock_images = [Path("image1.jpg"), Path("image2.png")]
        mock_get_images.return_value = mock_images
        
        result = get_random_image_from_folder("test_folder")
        
        assert result in mock_images
        mock_get_images.assert_called_once_with("test_folder")

    @patch("utils.quotes_utils.get_images_from_folder")
    def test_get_random_image_from_folder_error(self, mock_get_images):
        """Тест обработки ошибки при получении случайного изображения."""
        mock_get_images.side_effect = FolderNotFoundError("Folder not found")
        
        with pytest.raises(FolderNotFoundError):
            get_random_image_from_folder("nonexistent")


class TestSendRandomQuoteImage:
    """Тесты для функции send_random_quote_image."""

    @pytest.mark.asyncio
    @patch("utils.quotes_utils.get_random_image_from_folder")
    @patch("utils.quotes_utils.get_settings")
    @patch("builtins.open", create=True)
    async def test_send_random_quote_image_success(self, mock_open, mock_settings, mock_get_image):
        """Тест успешной отправки изображения."""
        # Настройка моков
        mock_settings.return_value.colors.default = "#0099ff"
        mock_image_path = MagicMock()
        mock_image_path.name = "test_image.jpg"
        mock_get_image.return_value = mock_image_path
        
        mock_file_handle = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file_handle
        
        # Создание мок контекста
        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        
        await send_random_quote_image(mock_ctx, "test_folder")
        
        # Проверки
        mock_get_image.assert_called_once_with("test_folder")
        mock_ctx.send.assert_called_once()
        
        # Проверяем, что send был вызван с embed и file
        call_args = mock_ctx.send.call_args
        assert "embed" in call_args.kwargs
        assert "file" in call_args.kwargs

    @pytest.mark.asyncio
    @patch("utils.quotes_utils.get_random_image_from_folder")
    @patch("utils.quotes_utils.get_settings")
    async def test_send_random_quote_image_folder_not_found(self, mock_settings, mock_get_image):
        """Тест отправки изображения из несуществующей папки."""
        mock_settings.return_value.colors.error = "#ff0000"
        mock_get_image.side_effect = FolderNotFoundError("Folder not found")
        
        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        
        await send_random_quote_image(mock_ctx, "nonexistent")
        
        # Проверяем, что отправлено сообщение об ошибке
        mock_ctx.send.assert_called_once()
        call_args = mock_ctx.send.call_args
        assert call_args.kwargs.get("ephemeral") is True


class TestGetFolderStats:
    """Тесты для функции get_folder_stats."""

    @patch("utils.quotes_utils.validate_folder_exists")
    def test_get_folder_stats_not_found(self, mock_validate):
        """Тест получения статистики несуществующей папки."""
        mock_validate.return_value = False
        
        result = get_folder_stats("nonexistent")
        
        assert result == {"total_images": 0, "by_extension": {}}

    @patch("utils.quotes_utils.validate_folder_exists")
    @patch("utils.quotes_utils.get_images_from_folder")
    def test_get_folder_stats_success(self, mock_get_images, mock_validate):
        """Тест успешного получения статистики папки."""
        mock_validate.return_value = True
        mock_images = [
            Path("image1.jpg"),
            Path("image2.jpg"),
            Path("image3.png"),
        ]
        mock_get_images.return_value = mock_images
        
        result = get_folder_stats("test_folder")
        
        expected = {
            "total_images": 3,
            "by_extension": {
                ".jpg": 2,
                ".png": 1,
            }
        }
        
        assert result == expected


class TestUIComponents:
    """Тесты для UI компонентов."""

    def test_quotes_folder_select_init(self):
        """Тест инициализации QuotesFolderSelect."""
        from utils.quotes_utils import QuotesFolderSelect
        
        mock_interaction = MagicMock()
        
        with patch("utils.quotes_utils.scan_quotes_folders") as mock_scan:
            with patch("utils.quotes_utils.get_settings") as mock_settings:
                mock_scan.return_value = ["folder1", "folder2"]
                mock_settings.return_value.fun.quotes.max_folders_in_select = 25
                
                select = QuotesFolderSelect(mock_interaction)
                
                assert select.original_interaction == mock_interaction
                assert len(select.options) == 2

    @pytest.mark.asyncio
    async def test_quotes_select_view_init(self):
        """Тест инициализации QuotesSelectView."""
        from utils.quotes_utils import QuotesSelectView
        
        mock_interaction = MagicMock()
        
        with patch("utils.quotes_utils.get_settings") as mock_settings:
            mock_settings.return_value.fun.quotes.view_timeout = 300
            
            view = QuotesSelectView(mock_interaction)
            
            assert view.original_interaction == mock_interaction
            assert view.timeout == 300.0
