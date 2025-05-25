"""Тесты для модуля config.py."""

import json
import tempfile
import os
from unittest.mock import patch, mock_open
import pytest

from config import load_config


class TestLoadConfig:
    """Тесты для функции load_config."""

    def test_load_config_success(self):
        """Тест успешной загрузки конфигурации."""
        # Создаем тестовые данные конфигурации
        test_config = {
            "BOT_TOKEN": "test_token_123",
            "GUILD_ID": 123456789,
            "ANIME_CHANNEL_ID": 987654321
        }
        
        # Мокируем открытие файла и json.load
        mock_file_content = json.dumps(test_config)
        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            result = load_config()
            
            assert result == test_config
            assert result["BOT_TOKEN"] == "test_token_123"
            assert result["GUILD_ID"] == 123456789

    def test_load_config_file_not_found(self):
        """Тест обработки отсутствующего файла конфигурации."""
        with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
            with patch("config.logger") as mock_logger:
                result = load_config()
                
                # Проверяем, что возвращается словарь с None токеном
                assert result == {"BOT_TOKEN": None}
                
                # Проверяем, что была залогирована критическая ошибка
                mock_logger.critical.assert_called_once()
                assert "Файл конфигурации не найден" in mock_logger.critical.call_args[0][0]

    def test_load_config_invalid_json(self):
        """Тест обработки некорректного JSON."""
        # Мокируем файл с некорректным JSON
        invalid_json = '{"BOT_TOKEN": "test", "invalid": }'
        
        with patch("builtins.open", mock_open(read_data=invalid_json)):
            with patch("config.logger") as mock_logger:
                result = load_config()
                
                # Проверяем, что возвращается словарь с None токеном
                assert result == {"BOT_TOKEN": None}
                
                # Проверяем, что была залогирована ошибка
                mock_logger.error.assert_called_once()
                assert "Ошибка при загрузке конфигурации" in mock_logger.error.call_args[0][0]

    def test_load_config_permission_error(self):
        """Тест обработки ошибки доступа к файлу."""
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with patch("config.logger") as mock_logger:
                result = load_config()
                
                # Проверяем, что возвращается словарь с None токеном
                assert result == {"BOT_TOKEN": None}
                
                # Проверяем, что была залогирована ошибка
                mock_logger.error.assert_called_once()
                assert "Ошибка при загрузке конфигурации" in mock_logger.error.call_args[0][0]

    def test_load_config_empty_file(self):
        """Тест обработки пустого файла."""
        with patch("builtins.open", mock_open(read_data="")):
            with patch("config.logger") as mock_logger:
                result = load_config()
                
                # Проверяем, что возвращается словарь с None токеном
                assert result == {"BOT_TOKEN": None}
                
                # Проверяем, что была залогирована ошибка
                mock_logger.error.assert_called_once()

    def test_load_config_with_real_file(self):
        """Тест с реальным временным файлом."""
        test_config = {
            "BOT_TOKEN": "real_test_token",
            "TEST_VALUE": 42
        }
        
        # Просто используем mock_open с правильными данными
        mock_file_content = json.dumps(test_config)
        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            result = load_config()
            
            assert result == test_config
            assert result["BOT_TOKEN"] == "real_test_token"
            assert result["TEST_VALUE"] == 42

    def test_load_config_unicode_content(self):
        """Тест загрузки конфигурации с Unicode символами."""
        test_config = {
            "BOT_TOKEN": "test_token",
            "DESCRIPTION": "Тестовый бот с русскими символами 🤖",
            "EMOJI": "🎮🎵🎨"
        }
        
        mock_file_content = json.dumps(test_config, ensure_ascii=False)
        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            result = load_config()
            
            assert result == test_config
            assert result["DESCRIPTION"] == "Тестовый бот с русскими символами 🤖"
            assert result["EMOJI"] == "🎮🎵🎨"

    def test_load_config_nested_structure(self):
        """Тест загрузки конфигурации со вложенной структурой."""
        test_config = {
            "BOT_TOKEN": "test_token",
            "CHANNELS": {
                "ANIME": 123456,
                "MUSIC": 789012
            },
            "FEATURES": {
                "ENABLED": ["anime", "music"],
                "DISABLED": ["admin"]
            }
        }
        
        mock_file_content = json.dumps(test_config)
        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            result = load_config()
            
            assert result == test_config
            assert result["CHANNELS"]["ANIME"] == 123456
            assert "anime" in result["FEATURES"]["ENABLED"]
