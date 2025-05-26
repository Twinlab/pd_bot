"""Тесты для main.py."""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


class TestMainWithNewConfig:
    """Тесты для main.py с новой системой конфигурации."""

    @pytest.mark.asyncio
    async def test_main_imports_successfully(self):
        """Тест успешного импорта main.py с новой конфигурацией."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            # Патчим YAML файл
            with patch("pathlib.Path.exists", return_value=False):
                # Патчим другие зависимости
                with patch("main.setup_logging"), \
                     patch("main.initialize_database"), \
                     patch("main.dota_api"):
                    
                    # Импортируем main после патчинга
                    import importlib
                    if 'main' in sys.modules:
                        importlib.reload(sys.modules['main'])
                    else:
                        import main
                    
                    # Проверяем, что основные объекты созданы
                    assert hasattr(main, 'settings')
                    assert hasattr(main, 'bot')
                    assert main.settings.bot_token == 'test_token'

    @pytest.mark.asyncio
    async def test_load_cogs_with_new_config(self):
        """Тест загрузки когов с новой системой конфигурации."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                # Создаем мок бота
                mock_bot = MagicMock()
                mock_bot.load_extension = AsyncMock()
                
                # Патчим зависимости
                with patch("main.setup_logging"), \
                     patch("main.initialize_database"), \
                     patch("main.dota_api"), \
                     patch("main.bot", mock_bot), \
                     patch("pathlib.Path.glob") as mock_glob:
                    
                    # Настраиваем мок для Path.glob
                    mock_glob.return_value = [
                        Path("cogs/admin.py"),
                        Path("cogs/activity.py"),
                        Path("cogs/__init__.py")
                    ]
                    
                    # Импортируем и вызываем функцию
                    import main
                    await main.load_cogs()
                    
                    # Проверяем, что load_extension был вызван
                    assert mock_bot.load_extension.call_count >= 2

    @pytest.mark.asyncio
    async def test_main_function_with_new_config(self):
        """Тест основной функции main с новой конфигурацией."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                # Создаем мок бота
                mock_bot = MagicMock()
                mock_bot.start = AsyncMock()
                
                # Патчим зависимости
                with patch("main.setup_logging"), \
                     patch("main.initialize_database", AsyncMock()) as mock_init_db, \
                     patch("main.dota_api.load_cache_from_disk", AsyncMock()) as mock_load_cache, \
                     patch("main.load_cogs", AsyncMock()) as mock_load_cogs, \
                     patch("main.bot", mock_bot):
                    
                    # Импортируем и вызываем функцию
                    import main
                    await main.main()
                    
                    # Проверяем, что все функции были вызваны
                    mock_init_db.assert_called_once()
                    mock_load_cache.assert_called_once()
                    mock_load_cogs.assert_called_once()
                    mock_bot.start.assert_called_once_with('test_token')

    def test_bot_creation_with_new_config(self):
        """Тест создания бота с новой системой конфигурации."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key',
            'BOT_PREFIX': '?'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("main.setup_logging"), \
                     patch("main.initialize_database"), \
                     patch("main.dota_api"):
                    
                    # Импортируем main
                    import importlib
                    if 'main' in sys.modules:
                        importlib.reload(sys.modules['main'])
                    else:
                        import main
                    
                    # Проверяем, что бот создан с правильным префиксом
                    assert main.bot.command_prefix == '?'
                    assert hasattr(main.bot, 'settings')
                    assert hasattr(main.bot, 'config')  # Обратная совместимость

    def test_config_compatibility_layer(self):
        """Тест слоя обратной совместимости конфигурации."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("main.setup_logging"), \
                     patch("main.initialize_database"), \
                     patch("main.dota_api"):
                    
                    # Импортируем main
                    import importlib
                    if 'main' in sys.modules:
                        importlib.reload(sys.modules['main'])
                    else:
                        import main
                    
                    # Проверяем, что словарь config содержит нужные ключи
                    assert 'BOT_TOKEN' in main.config
                    assert 'STRATZ_API_KEY' in main.config
                    assert 'PREFIX' in main.config
                    assert 'LOGGING_CHANNEL_ID' in main.config
                    
                    # Проверяем значения
                    assert main.config['BOT_TOKEN'] == 'test_token'
                    assert main.config['STRATZ_API_KEY'] == 'test_key'

    @pytest.mark.asyncio
    async def test_error_handling_in_main(self):
        """Тест обработки ошибок в функции main."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                # Создаем мок бота с ошибкой
                mock_bot = MagicMock()
                mock_bot.start = AsyncMock(side_effect=Exception("Test error"))
                
                # Патчим зависимости
                with patch("main.setup_logging"), \
                     patch("main.initialize_database", AsyncMock()), \
                     patch("main.dota_api.load_cache_from_disk", AsyncMock()), \
                     patch("main.load_cogs", AsyncMock()), \
                     patch("main.bot", mock_bot), \
                     patch("main.logger") as mock_logger:
                    
                    # Импортируем и вызываем функцию
                    import main
                    await main.main()
                    
                    # Проверяем, что ошибка была залогирована
                    mock_logger.critical.assert_called_once()
                    assert "Не удалось запустить бота" in str(mock_logger.critical.call_args)
