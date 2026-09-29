"""Публичные функции рендера wrapped-карточек."""

from collections.abc import Callable

from .builder import PersonalWrapped, ServerWrapped
from .cards import render_personal, render_server

Avatars = dict[int, bytes] | None


def render_server_card(
    summary: ServerWrapped, names: Callable[[int], str], avatars: Avatars = None
) -> bytes:
    """Возвращает серверный wrapped в PNG.

    Args:
        summary: Сводка за месяц или год.
        names: Отображаемые имена участников по ID.
        avatars: Загруженные изображения аватаров по ID.
    """
    return render_server(summary, names, avatars)


def render_personal_card(
    personal: PersonalWrapped, name: str, avatar: bytes | None = None
) -> bytes:
    """Возвращает личный годовой wrapped в PNG.

    Args:
        personal: Годовая статистика участника.
        name: Отображаемое имя.
        avatar: Загруженный аватар; при отсутствии используется инициал.
    """
    return render_personal(personal, name, avatar)
