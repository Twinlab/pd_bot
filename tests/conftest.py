"""Конфигурационный файл для pytest, содержит фикстуры и хуки."""

import sys
from pathlib import Path

# Добавляем корень проекта в sys.path для корректного импорта модулей (utils, cogs, handlers)
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
