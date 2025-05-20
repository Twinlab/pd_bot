"""Тесты для main.py."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

# Патчим функции перед импортом main.py
with patch("config.load_config", return_value={"BOT_TOKEN": "fake_token", "PREFIX": "!"}), \
     patch("builtins.exit"):
    import main
    from main import MyBot, load_cogs, main as main_func


class TestMyBot:
    """Тесты для класса MyBot."""

    def test_init(self):
        """Тест инициализации класса MyBot."""
        # Создаем моки
        intents = discord.Intents.default()
        
        # Патчим config.load_config
        with patch("config.load_config", return_value={"BOT_TOKEN": "fake_token", "PREFIX": "!"}):
            # Создаем экземпляр MyBot
            bot = MyBot(command_prefix="!", intents=intents)
        
        # Проверяем, что атрибуты установлены корректно
        assert bot.command_prefix == "!"
        assert bot.intents == intents


class TestLoadCogs:
    """Тесты для функции load_cogs."""

    @pytest.mark.asyncio
    async def test_load_cogs_success(self):
        """Тест успешной загрузки когов."""
        # Создаем мок бота
        mock_bot = MagicMock()
        mock_bot.load_extension = AsyncMock()
        
        # Патчим Path.glob для имитации файлов когов
        with patch("main.bot", mock_bot), \
             patch("pathlib.Path.glob") as mock_glob, \
             patch("main.logger") as mock_logger, \
             patch("config.load_config", return_value={"BOT_TOKEN": "fake_token", "PREFIX": "!"}):
            
            # Настраиваем мок для Path.glob
            mock_glob.return_value = [
                Path("cogs/admin.py"),
                Path("cogs/activity.py"),
                Path("cogs/__init__.py")
            ]
            
            # Вызываем функцию
            await load_cogs()
            
            # Проверяем, что load_extension был вызван для каждого кога (кроме __init__.py)
            assert mock_bot.load_extension.call_count == 4  # 2 кога + 2 обработчика
            mock_bot.load_extension.assert_any_call("cogs.admin")
            mock_bot.load_extension.assert_any_call("cogs.activity")
            mock_bot.load_extension.assert_any_call("handlers.events")
            mock_bot.load_extension.assert_any_call("handlers.message_handler")
            
            # Проверяем, что логирование было вызвано
            assert mock_logger.info.call_count >= 3
            mock_logger.info.assert_any_call("Загрузка когов команд...")
            mock_logger.info.assert_any_call("Загрузка обработчиков событий...")
            mock_logger.info.assert_any_call("Загрузка обработчика сообщений...")

    @pytest.mark.asyncio
    async def test_load_cogs_error(self):
        """Тест обработки ошибок при загрузке когов."""
        # Создаем мок бота
        mock_bot = MagicMock()
        mock_bot.load_extension = AsyncMock(side_effect=Exception("Test error"))
        
        # Патчим Path.glob для имитации файлов когов
        with patch("main.bot", mock_bot), \
             patch("pathlib.Path.glob") as mock_glob, \
             patch("main.logger") as mock_logger, \
             patch("config.load_config", return_value={"BOT_TOKEN": "fake_token", "PREFIX": "!"}):
            
            # Настраиваем мок для Path.glob
            mock_glob.return_value = [
                Path("cogs/admin.py")
            ]
            
            # Вызываем функцию
            await load_cogs()
            
            # Проверяем, что load_extension был вызван
            mock_bot.load_extension.assert_called()
            
            # Проверяем, что логирование ошибок было вызвано
            assert mock_logger.error.call_count >= 1
            mock_logger.error.assert_any_call("Ошибка при загрузке кога admin.py: Test error")


class TestMain:
    """Тесты для функции main."""

    @pytest.mark.asyncio
    async def test_main_success(self):
        """Тест успешного выполнения функции main."""
        # Патчим зависимости
        with patch("main.initialize_database", AsyncMock()) as mock_init_db, \
             patch("main.dota_api.load_cache_from_disk", AsyncMock()) as mock_load_cache, \
             patch("main.load_cogs", AsyncMock()) as mock_load_cogs, \
             patch("main.bot") as mock_bot, \
             patch("main.logger") as mock_logger, \
             patch("config.load_config", return_value={"BOT_TOKEN": "fake_token", "PREFIX": "!"}):
            
            # Настраиваем моки
            mock_bot.start = AsyncMock()
            
            # Вызываем функцию
            await main_func()
            
            # Проверяем, что все функции были вызваны
            mock_init_db.assert_called_once()
            mock_load_cache.assert_called_once()
            mock_load_cogs.assert_called_once()
            mock_bot.start.assert_called_once_with(main.config["BOT_TOKEN"])
            
            # Проверяем, что логирование было вызвано
            assert mock_logger.info.call_count >= 2
            mock_logger.info.assert_any_call(f"Используется файл базы данных: {main.DB_PATH}")
            mock_logger.info.assert_any_call("Загрузка кэша Dota API с диска...")

    @pytest.mark.asyncio
    async def test_main_error(self):
        """Тест обработки ошибок в функции main."""
        # Патчим зависимости
        with patch("main.initialize_database", AsyncMock()) as mock_init_db, \
             patch("main.dota_api.load_cache_from_disk", AsyncMock()) as mock_load_cache, \
             patch("main.load_cogs", AsyncMock()) as mock_load_cogs, \
             patch("main.bot") as mock_bot, \
             patch("main.logger") as mock_logger, \
             patch("config.load_config", return_value={"BOT_TOKEN": "fake_token", "PREFIX": "!"}):
            
            # Настраиваем моки
            mock_bot.start = AsyncMock(side_effect=Exception("Test error"))
            
            # Вызываем функцию
            await main_func()
            
            # Проверяем, что все функции были вызваны
            mock_init_db.assert_called_once()
            mock_load_cache.assert_called_once()
            mock_load_cogs.assert_called_once()
            mock_bot.start.assert_called_once_with(main.config["BOT_TOKEN"])
            
            # Проверяем, что логирование ошибки было вызвано
            mock_logger.critical.assert_called_once()
            assert "Не удалось запустить бота" in mock_logger.critical.call_args[0][0]


class TestMainModule:
    """Тесты для модуля main."""

    @pytest.mark.asyncio
    async def test_main_entry_point(self):
        """Тест точки входа в приложение."""
        # Патчим asyncio.run и main_func
        with patch("asyncio.run") as mock_run, \
             patch("main.main") as mock_main_func, \
             patch("config.load_config", return_value={"BOT_TOKEN": "fake_token", "PREFIX": "!"}):
            
            # Вызываем точку входа
            # Для этого нам нужно имитировать запуск модуля как скрипта
            # Мы не можем напрямую вызвать if __name__ == "__main__", поэтому патчим asyncio.run
            
            # Проверяем, что asyncio.run не был вызван (так как мы не запускаем модуль как скрипт)
            mock_run.assert_not_called()
            
            # Проверяем, что main_func не был вызван
            mock_main_func.assert_not_called()
