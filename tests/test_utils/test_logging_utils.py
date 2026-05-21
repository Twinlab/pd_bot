"""Тесты для модуля logging_utils."""

import json
import logging
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from utils.logging_utils import JsonFormatter, cleanup_old_logs, setup_logging, with_context


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


class TestCleanupOldLogs:
    """Тесты для функции cleanup_old_logs."""

    def _make_log(self, log_dir: Path, name: str, age_days: float) -> Path:
        """Создаёт пустой лог-файл с mtime, отстающим на age_days дней назад."""
        path = log_dir / name
        path.write_text("")
        ts = time.time() - age_days * 86400
        os.utime(path, (ts, ts))
        return path

    def test_cleanup_skips_nonexistent_dir(self, tmp_path):
        removed = cleanup_old_logs(tmp_path / "missing")
        assert removed == 0

    def test_cleanup_removes_old_files(self, tmp_path):
        old = self._make_log(tmp_path, "2024-01-01_00-00-00.log", age_days=30)
        fresh = self._make_log(tmp_path, "2026-05-21_12-00-00.log", age_days=0)

        removed = cleanup_old_logs(tmp_path, max_age_days=14, max_files=30)

        assert removed == 1
        assert not old.exists()
        assert fresh.exists()

    def test_cleanup_keeps_only_max_files(self, tmp_path):
        # Создаём 5 свежих файлов, max_files=3 → удалится 2 самых старых.
        files = [
            self._make_log(tmp_path, f"2026-05-1{i}_12-00-00.log", age_days=5 - i)
            for i in range(5)
        ]
        # files[0] — самый старый по mtime, files[4] — самый свежий.

        removed = cleanup_old_logs(tmp_path, max_age_days=365, max_files=3)

        assert removed == 2
        # Должны остаться 3 самых свежих.
        remaining = sorted(p.name for p in tmp_path.iterdir())
        assert len(remaining) == 3
        assert files[0].exists() is False
        assert files[1].exists() is False
        assert files[4].exists() is True

    def test_cleanup_ignores_unrelated_files(self, tmp_path):
        # Эти файлы не должны удаляться, даже если они старые.
        unrelated = tmp_path / "latest.log"
        unrelated.write_text("symlink target placeholder")
        ts = time.time() - 365 * 86400
        os.utime(unrelated, (ts, ts))

        readme = tmp_path / "README.md"
        readme.write_text("# logs")
        os.utime(readme, (ts, ts))

        removed = cleanup_old_logs(tmp_path, max_age_days=14)

        assert removed == 0
        assert unrelated.exists()
        assert readme.exists()

    def test_cleanup_handles_unlink_oserror(self, tmp_path):
        old = self._make_log(tmp_path, "2024-01-01_00-00-00.log", age_days=30)

        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            removed = cleanup_old_logs(tmp_path, max_age_days=14)

        assert removed == 0
        assert old.exists()


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
