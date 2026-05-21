"""Утилиты для расширенного логирования."""

import json
import logging
import os
import re
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar, cast

import colorlog

# Типы для аннотаций
F = TypeVar("F", bound=Callable[..., Any])

# Настройка логгера для модуля
logger = logging.getLogger("bot.utils.logging_utils")

# Параметры ретеншена логов: каждый рестарт бота создаёт новый файл, поэтому
# простой RotatingFileHandler здесь не подходит. Удаляем старые файлы при старте.
LOG_RETENTION_DAYS = 14
LOG_RETENTION_MAX_FILES = 30

# Имена файлов логов: "YYYY-MM-DD_HH-MM-SS.log".
_LOG_FILENAME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log$")


# Класс для JSON-форматирования логов
class JsonFormatter(logging.Formatter):
    """Форматирует логи в JSON формате для удобного анализа."""

    def format(self, record: logging.LogRecord) -> str:
        """
        Форматирует запись лога в JSON.

        Args:
            record: Запись лога.

        Returns:
            Строка в формате JSON.
        """
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Добавляем контекст, если он есть
        if hasattr(record, "context") and record.context:
            log_data["context"] = record.context

        # Добавляем информацию об исключении, если оно есть
        if record.exc_info and record.exc_info[0] is not None:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(log_data)


def cleanup_old_logs(
    log_dir: Path,
    max_age_days: int = LOG_RETENTION_DAYS,
    max_files: int = LOG_RETENTION_MAX_FILES,
) -> int:
    """Удаляет старые лог-файлы, чтобы они не заполняли диск.

    Удаляются только файлы, у которых имя соответствует шаблону рестарт-логов
    (`YYYY-MM-DD_HH-MM-SS.log`), чтобы случайно не зацепить чужие файлы и
    симлинк `latest.log`.

    Применяются два правила (любое из них достаточно для удаления):
        - файл старше `max_age_days` (по mtime);
        - файл выпал из топ-`max_files` самых свежих по mtime.

    Args:
        log_dir: Директория с логами.
        max_age_days: Максимальный возраст файла в днях.
        max_files: Сколько последних файлов оставить.

    Returns:
        Количество удалённых файлов.
    """
    if not log_dir.is_dir():
        return 0

    candidates = [
        path
        for path in log_dir.iterdir()
        if path.is_file() and _LOG_FILENAME_PATTERN.match(path.name)
    ]
    if not candidates:
        return 0

    # Сортируем по времени последней модификации, новые — первыми.
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    cutoff_ts = time.time() - max_age_days * 86400
    removed = 0

    for index, path in enumerate(candidates):
        too_old = path.stat().st_mtime < cutoff_ts
        too_many = index >= max_files
        if not (too_old or too_many):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("Не удалось удалить старый лог %s: %s", path, exc)

    if removed:
        logger.info("Удалено старых лог-файлов: %s", removed)

    return removed


def setup_logging(
    log_dir: str = "logs",
    log_level: int = logging.INFO,
    enable_json_logs: bool = True,
    enable_console_logs: bool = True,
) -> Path:
    """
    Настраивает систему логирования с расширенными возможностями.

    Args:
        log_dir: Директория для хранения логов.
        log_level: Уровень логирования.
        enable_json_logs: Включить JSON-логи.
        enable_console_logs: Включить вывод в консоль.
    """
    # Создаем директорию для логов, если она не существует
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(exist_ok=True)

    # Подчищаем старые лог-файлы, чтобы директория не разрасталась бесконечно.
    # Делаем это до создания нового файла, чтобы не удалить только что созданный.
    try:
        cleanup_old_logs(log_dir_path)
    except Exception as exc:
        # Не фейлим запуск из-за проблем с уборкой логов.
        logger.warning("Ошибка при очистке старых логов: %s", exc)

    # Создаем уникальное имя файла для текущего запуска
    log_filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S.log")
    log_path = log_dir_path / log_filename

    # Создаем/обновляем симлинк на последний лог
    latest_symlink = log_dir_path / "latest.log"
    try:
        if latest_symlink.exists() or latest_symlink.is_symlink():
            latest_symlink.unlink(missing_ok=True)
        latest_symlink.symlink_to(log_filename)
    except OSError as e:
        logger.error(f"Не удалось создать/обновить симлинк 'latest.log': {e}")

    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Очищаем существующие обработчики
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Добавляем обработчик для файла
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")

    if enable_json_logs:
        file_handler.setFormatter(JsonFormatter())
    else:
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    root_logger.addHandler(file_handler)

    # Добавляем обработчик для консоли, если нужно
    if enable_console_logs:
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(
            colorlog.ColoredFormatter(
                "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                log_colors={
                    "DEBUG": "cyan",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "red,bg_white",
                },
            )
        )
        root_logger.addHandler(console_handler)

    # Логируем информацию о запуске
    logger.info(f"Логирование настроено. Файл логов: {log_path}")
    logger.info(f"Версия Python: {sys.version}")
    logger.info(f"Операционная система: {os.name} {sys.platform}")

    return log_path


def with_context(logger: logging.Logger, context: dict[str, Any]) -> Callable[[F], F]:
    """
    Декоратор для добавления контекста к логам внутри функции.

    Args:
        logger: Логгер для использования.
        context: Словарь с контекстной информацией.

    Returns:
        Декорированная функция.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Создаем фильтр для добавления контекста
            class ContextFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    record.context = context  # type: ignore
                    return True

            # Добавляем фильтр к логгеру
            context_filter = ContextFilter()
            logger.addFilter(context_filter)

            try:
                return func(*args, **kwargs)
            finally:
                # Удаляем фильтр после выполнения функции
                logger.removeFilter(context_filter)

        return cast(F, wrapper)

    return decorator
