"""Снимок проверенных Python-зависимостей для одной сборки образа."""

import argparse
import logging
import re
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path

logger = logging.getLogger("bot.build.dependencies")
_PIN = re.compile(r"([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)==([0-9][A-Za-z0-9.!+_-]*)")
_PROJECT = "pd-bot"


def _name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def installed_versions(distributions: Iterable[metadata.Distribution]) -> dict[str, str]:
    """Собрать версии без локального проекта и непереносимых URL-зависимостей."""
    versions: dict[str, str] = {}
    for distribution in distributions:
        name = _name(distribution.metadata["Name"] or "")
        if name == _PROJECT:
            continue
        version = distribution.version
        if not _PIN.fullmatch(f"{name}=={version}"):
            raise ValueError("Некорректные имя или версия установленного пакета")
        if distribution.read_text("direct_url.json") is not None:
            raise ValueError(f"URL-зависимость не поддерживается: {name}")
        if name in versions:
            raise ValueError(f"Пакет установлен несколько раз: {name}")
        versions[name] = version
    if not versions:
        raise ValueError("Окружение не содержит зависимостей")
    return versions


def read_snapshot(path: Path) -> dict[str, str]:
    """Прочитать только точные pins, отклоняя URL, диапазоны и дубликаты."""
    versions: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = _PIN.fullmatch(line)
        if match is None:
            raise ValueError(f"Некорректный pin в строке {number}")
        name, version = _name(match[1]), match[2]
        if name == _PROJECT or name in versions:
            raise ValueError(f"Недопустимый или повторный пакет в строке {number}")
        versions[name] = version
    if not versions:
        raise ValueError("Снимок зависимостей пуст")
    return versions


def write_snapshot(path: Path, versions: dict[str, str]) -> None:
    """Сохранить переносимый список версий без путей и метаданных источников."""
    path.write_text(
        "".join(f"{name}=={version}\n" for name, version in sorted(versions.items())),
        encoding="utf-8",
        newline="\n",
    )


def check_snapshot(expected: dict[str, str], installed: dict[str, str]) -> None:
    """Проверить runtime-подмножество снимка; dev-пакеты в образе не обязательны."""
    for name, version in installed.items():
        if name not in expected:
            raise ValueError(f"Установлен пакет вне снимка: {name}")
        if expected[name] != version:
            raise ValueError(
                f"Версия {name} не совпадает: установлена {version}, ожидалась {expected[name]}"
            )


def main(argv: list[str] | None = None) -> int:
    """Записать снимок окружения или проверить установленный набор по снимку."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "check", "validate"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            read_snapshot(args.path)
            logger.info("Синтаксис снимка проверен")
            return 0
        versions = installed_versions(metadata.distributions())
        if args.command == "write":
            write_snapshot(args.path, versions)
        else:
            check_snapshot(read_snapshot(args.path), versions)
    except (OSError, ValueError) as exc:
        logger.error("Проверка зависимостей не выполнена: %s", exc)
        return 1
    logger.info("%s: %s пакетов", args.command, len(versions))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
