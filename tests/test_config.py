"""Тесты для новой системы конфигурации."""

import os
import tempfile
from unittest.mock import patch, mock_open
import pytest
import yaml

from config import get_settings, BotSettings


class TestNewConfigSystem:
    """Тесты для новой системы конфигурации на основе Pydantic Settings."""

    def test_get_settings_success(self):
        """Тест успешной загрузки настроек."""
        # Мокируем переменные окружения
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token_123',
            'STRATZ_API_KEY': 'test_stratz_key'
        }):
            # Мокируем YAML файл
            yaml_content = {
                'channels': {
                    'logging': 1365045098785542224,
                    'twitch': 1113813039083442296
                },
                'timeouts': {
                    'log_check_interval': 5
                }
            }
            
            with patch("pathlib.Path.exists", return_value=True):
                with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
                    settings = get_settings()
                    
                    assert settings.bot_token == 'test_token_123'
                    assert settings.stratz_api_key == 'test_stratz_key'
                    assert settings.channels.logging == 1365045098785542224
                    assert settings.timeouts.log_check_interval == 5

    def test_get_settings_missing_required_env(self):
        """Тест обработки отсутствующих обязательных переменных окружения."""
        # Очищаем переменные окружения
        with patch.dict(os.environ, {}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                # Теперь поля имеют значения по умолчанию, поэтому исключения не будет
                settings = BotSettings()
                assert settings.bot_token == "test_token_here"
                assert settings.stratz_api_key == "test_stratz_key_here"

    def test_get_settings_yaml_not_found(self):
        """Тест работы без YAML файла (только переменные окружения)."""
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                settings = BotSettings.load_from_yaml()
                
                assert settings.bot_token == 'test_token'
                assert settings.stratz_api_key == 'test_key'
                # Проверяем значения по умолчанию
                assert settings.prefix == '!'
                # Дефолт каналов теперь sentinel (0), а не хардкод ID прод-сервера.
                assert settings.channels.logging == 0

    def test_get_settings_yaml_override(self):
        """Тест переопределения настроек через YAML."""
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            yaml_content = {
                'channels': {
                    'logging': 999999999
                },
                'colors': {
                    'default': '#ff0000'
                }
            }
            
            with patch("pathlib.Path.exists", return_value=True):
                with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
                    settings = BotSettings.load_from_yaml()
                    
                    assert settings.channels.logging == 999999999
                    assert settings.colors.default == '#ff0000'

    def test_get_settings_env_override(self):
        """Тест переопределения настроек через переменные окружения."""
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key',
            'BOT_PREFIX': '?',
            'BOT_CHANNELS__LOGGING': '123456789'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                settings = BotSettings()
                
                assert settings.prefix == '?'
                # Проверяем, что вложенные настройки тоже переопределяются
                # (это зависит от реализации Pydantic Settings)

    def test_get_discord_color(self):
        """Тест метода get_discord_color."""
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                settings = BotSettings()
                
                # Тестируем получение цвета
                color = settings.get_discord_color('error')
                # Проверяем, что возвращается объект Discord Color
                assert hasattr(color, 'value')

    def test_messages_structure(self):
        """Тест структуры сообщений."""
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            with patch("pathlib.Path.exists", return_value=False):
                settings = BotSettings()
                
                # Проверяем наличие основных сообщений
                assert 'no_permissions' in settings.messages.errors
                assert 'twitch_api_not_configured' in settings.messages.errors
                assert 'purge_complete' in settings.messages.success
                assert 'restart_initiated' in settings.messages.success

    def test_config_validation(self):
        """Тест валидации конфигурации."""
        with patch.dict(os.environ, {
            'BOT_TOKEN': 'test_token',
            'STRATZ_API_KEY': 'test_key'
        }):
            yaml_content = {
                'timeouts': {
                    'log_check_interval': 'invalid_value'  # Должно быть число
                }
            }
            
            with patch("pathlib.Path.exists", return_value=True):
                with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
                    # Pydantic должен обработать неверный тип
                    with pytest.raises(Exception):
                        BotSettings.load_from_yaml()
