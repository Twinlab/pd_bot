"""Регрессия на конфликт имён/алиасов команд между когами.

История: до этого теста на проде падало
``CommandRegistrationError: clear is already an existing command`` —
``MusicCog`` и ``AdminCog`` оба объявляли команду ``clear``. Тест ловит
такие столкновения статически (на уровне ``__cog_commands__``), без
поднятия event loop, БД или Lavalink, поэтому он быстрый и надёжный.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict

from discord.ext import commands

import cogs as cogs_pkg


def _all_cog_classes() -> list[type[commands.Cog]]:
    """Импортирует все модули пакета cogs и возвращает их Cog-классы."""
    classes: list[type[commands.Cog]] = []
    for module_info in pkgutil.iter_modules(cogs_pkg.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"cogs.{module_info.name}")
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, commands.Cog)
                and obj is not commands.Cog
                and obj.__module__ == module.__name__
            ):
                classes.append(obj)
    return classes


def _walk_commands(cmd: commands.Command) -> list[commands.Command]:
    """Рекурсивно обходит команду и её подкоманды (если это группа)."""
    result: list[commands.Command] = [cmd]
    if isinstance(cmd, commands.Group):
        for sub in cmd.commands:
            result.extend(_walk_commands(sub))
    return result


def test_no_command_name_or_alias_clash_between_cogs() -> None:
    """Каждое имя/алиас команды должно быть уникальным по всему проекту.

    Алиасы учитываются наравне с основным именем — discord.py при регистрации
    кладёт их в один и тот же ``Bot.all_commands`` dict, поэтому конфликт
    между алиасом и чужим именем тоже валит старт бота.
    """
    cog_classes = _all_cog_classes()
    assert cog_classes, "Не нашли ни одного Cog-класса в пакете cogs/"

    occupants: dict[str, list[str]] = defaultdict(list)
    for cog_cls in cog_classes:
        for top_cmd in cog_cls.__cog_commands__:
            for cmd in _walk_commands(top_cmd):
                origin = f"{cog_cls.__name__}.{cmd.qualified_name}"
                for name in (cmd.name, *cmd.aliases):
                    occupants[name].append(origin)

    clashes = {name: origins for name, origins in occupants.items() if len(origins) > 1}
    assert not clashes, "Конфликт имён/алиасов команд между когами: " + ", ".join(
        f"{name!r} → {origins}" for name, origins in clashes.items()
    )


def test_clear_belongs_to_admin_only() -> None:
    """Точечная проверка регрессии: `clear` живёт только в AdminCog.

    Если кто-то снова заведёт команду или алиас `clear` в другом коге — этот
    тест упадёт с понятной диагностикой ещё до общего теста выше.
    """
    cog_classes = _all_cog_classes()
    owners: list[str] = []
    for cog_cls in cog_classes:
        for top_cmd in cog_cls.__cog_commands__:
            for cmd in _walk_commands(top_cmd):
                if "clear" in (cmd.name, *cmd.aliases):
                    owners.append(f"{cog_cls.__name__}.{cmd.qualified_name}")

    assert owners == ["AdminCog.clear"], f"Неожиданные владельцы 'clear': {owners}"
