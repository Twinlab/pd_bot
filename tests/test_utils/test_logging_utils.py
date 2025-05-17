"""Тесты для модуля logging_utils."""

import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from utils.logging_utils import JsonFormatter, setup_logging, with_context


class TestJsonFormatter:
    """Тесты для класса JsonFormatter."""

    def test_json_formatter_basic(self):
        """Тест форматирования обычного лога."""
        # Создаем форматтер
        formatter = JsonFormatter()

        # Создаем запись лога
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test_path",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Форматируем запись
        formatted = formatter.format(record)

        # Проверяем, что результат - валидный JSON
        log_data = json.loads(formatted)

        # Проверяем содержимое
        assert log_data["logger"] == "test_logger"
        assert log_data["level"] == "INFO"
        assert log_data["message"] == "Test message"
        assert log_data["line"] == 42
        assert "timestamp" in log_data
        assert "module" in log_data
        assert "function" in log_data

    def test_json_formatter_with_context(self):
        """Тест форматирования лога с контекстом."""
        # Создаем форматтер
        formatter = JsonFormatter()

        # Создаем запись лога с контекстом
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test_path",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.context = {"user_id": 123, "guild_id": 456}

        # Форматируем запись
        formatted = formatter.format(record)

        # Проверяем, что результат - валидный JSON
        log_data = json.loads(formatted)

        # Проверяем содержимое
        assert log_data["context"]["user_id"] == 123
        assert log_data["context"]["guild_id"] == 456

    def test_json_formatter_with_exception(self):
        """Тест форматирования лога с исключением."""
        # Создаем форматтер
        formatter = JsonFormatter()

        # Создаем исключение
        try:
            raise ValueError("Test exception")
        except ValueError:
            exc_info = sys.exc_info()

        # Создаем запись лога с исключением
        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test_path",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=exc_info,
        )

        # Форматируем запись
        formatted = formatter.format(record)

        # Проверяем, что результат - валидный JSON
        log_data = json.loads(formatted)

        # Проверяем содержимое
        assert log_data["exception"]["type"] == "ValueError"
        assert log_data["exception"]["message"] == "Test exception"
        assert isinstance(log_data["exception"]["traceback"], list)


class TestSetupLogging:
    """Тесты для функции setup_logging."""

    def test_setup_logging_basic(self, tmp_path):
        """Тест базовой настройки логирования."""
        # Создаем временную директорию для логов
        log_dir = tmp_path / "logs"

        # Патчим логгер и другие функции
        with patch("utils.logging_utils.logger") as mock_logger, patch(
            "utils.logging_utils.logging.FileHandler"
        ) as mock_file_handler, patch("utils.logging_utils.logging.getLogger") as mock_get_logger:
            # Настраиваем моки
            mock_root_logger = MagicMock()
            mock_get_logger.return_value = mock_root_logger

            # Вызываем функцию
            log_path = setup_logging(log_dir=str(log_dir))

            # Проверяем результат
            assert log_path.parent == log_dir
            assert log_path.name.endswith(".log")
            mock_logger.info.assert_called()
            mock_file_handler.assert_called_once()
            mock_root_logger.addHandler.assert_called()

    @pytest.mark.parametrize(
        "enable_json_logs,enable_console_logs",
        [
            (True, True),
            (True, False),
            (False, True),
            (False, False),
        ],
    )
    def test_setup_logging_parameters(self, tmp_path, enable_json_logs, enable_console_logs):
        """Тест настройки с разными параметрами."""
        # Создаем временную директорию для логов
        log_dir = tmp_path / "logs"

        # Патчим логгер и другие функции
        with patch("utils.logging_utils.logger"), patch(
            "utils.logging_utils.logging.FileHandler"
        ) as mock_file_handler, patch(
            "utils.logging_utils.colorlog.StreamHandler"
        ) as mock_stream_handler, patch(
            "utils.logging_utils.JsonFormatter"
        ) as mock_json_formatter, patch(
            "utils.logging_utils.logging.Formatter"
        ) as mock_formatter, patch(
            "utils.logging_utils.logging.getLogger"
        ) as mock_get_logger:
            # Настраиваем моки
            mock_root_logger = MagicMock()
            mock_get_logger.return_value = mock_root_logger

            # Вызываем функцию
            setup_logging(
                log_dir=str(log_dir),
                log_level=logging.DEBUG,
                enable_json_logs=enable_json_logs,
                enable_console_logs=enable_console_logs,
            )

            # Проверяем результат
            mock_file_handler.assert_called_once()

            if enable_json_logs:
                mock_json_formatter.assert_called_once()
            else:
                mock_formatter.assert_called_once()

            if enable_console_logs:
                mock_stream_handler.assert_called_once()
            else:
                mock_stream_handler.assert_not_called()

    def test_setup_logging_symlink_error(self, tmp_path):
        """Тест обработки ошибок при создании симлинка."""
        # Создаем временную директорию для логов
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        # Патчим функцию symlink_to, чтобы она вызывала исключение
        with patch("pathlib.Path.symlink_to", side_effect=OSError("Test error")), patch(
            "utils.logging_utils.logger"
        ) as mock_logger, patch("utils.logging_utils.logging.getLogger") as mock_get_logger:
            # Настраиваем моки
            mock_root_logger = MagicMock()
            mock_get_logger.return_value = mock_root_logger

            # Вызываем функцию
            setup_logging(log_dir=str(log_dir))

            # Проверяем, что ошибка обработана
            mock_logger.error.assert_called_once()
            assert "Test error" in mock_logger.error.call_args[0][0]


class TestWithContext:
    """Тесты для декоратора with_context."""

    @pytest.mark.asyncio
    async def test_with_context(self):
        """Тест добавления контекста к логам."""
        # Создаем логгер
        logger = logging.getLogger("test_logger")

        # Создаем контекст
        context = {"user_id": 123, "guild_id": 456}

        # Создаем функцию для декорирования
        async def test_function():
            logger.info("Test message")
            return "result"

        # Патчим логгер
        with patch.object(logger, "addFilter") as mock_add_filter, patch.object(
            logger, "removeFilter"
        ) as mock_remove_filter:
            # Декорируем функцию
            decorated = with_context(logger, context)(test_function)

            # Вызываем декорированную функцию
            result = await decorated()

            # Проверяем результат
            assert result == "result"
            mock_add_filter.assert_called_once()
            mock_remove_filter.assert_called_once()

            # Проверяем, что фильтр добавляет контекст
            filter_obj = mock_add_filter.call_args[0][0]
            record = MagicMock()
            filter_obj.filter(record)
            assert record.context == context

    @pytest.mark.asyncio
    async def test_with_context_exception(self):
        """Тест обработки исключений."""
        # Создаем логгер
        logger = logging.getLogger("test_logger")

        # Создаем контекст
        context = {"user_id": 123, "guild_id": 456}

        # Создаем функцию, которая вызывает исключение
        async def test_function():
            raise ValueError("Test exception")

        # Патчим логгер
        with patch.object(logger, "addFilter") as mock_add_filter, patch.object(
            logger, "removeFilter"
        ) as mock_remove_filter:
            # Декорируем функцию
            decorated = with_context(logger, context)(test_function)

            # Вызываем декорированную функцию и проверяем, что исключение проброшено
            with pytest.raises(ValueError, match="Test exception"):
                await decorated()

            # Проверяем, что фильтр был добавлен и удален
            mock_add_filter.assert_called_once()
            mock_remove_filter.assert_called_once()
