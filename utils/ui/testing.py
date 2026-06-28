"""Ассерт-хелперы для тестов Components V2.

Единый способ заглянуть внутрь ``LayoutView`` (текст/картинки/ссылки/акцент),
чтобы зеркальные тесты CV2-миграций писались одинаково, а не каждый по-своему
ковырял ``walk_children()``.
"""

from __future__ import annotations

import discord


def text_blocks(view: discord.ui.LayoutView) -> list[str]:
    """Содержимое всех ``TextDisplay`` в порядке обхода дерева."""
    return [c.content for c in view.walk_children() if isinstance(c, discord.ui.TextDisplay)]


def joined_text(view: discord.ui.LayoutView) -> str:
    """Весь текст карточки одной строкой — удобно для проверок через ``in``."""
    return "\n".join(text_blocks(view))


def media_sources(view: discord.ui.LayoutView) -> list[str]:
    """Источники (url / ``attachment://``) всех картинок в ``MediaGallery``."""
    sources: list[str] = []
    for child in view.walk_children():
        if isinstance(child, discord.ui.MediaGallery):
            sources.extend(item.media.url for item in child.items)
    return sources


def link_buttons(view: discord.ui.LayoutView) -> list[tuple[str | None, str | None]]:
    """Пары ``(label, url)`` всех кнопок-ссылок."""
    return [
        (child.label, child.url)
        for child in view.walk_children()
        if isinstance(child, discord.ui.Button) and child.style is discord.ButtonStyle.link
    ]


def accent_colours(view: discord.ui.LayoutView) -> list[discord.Colour | int | None]:
    """Акцент-цвета всех контейнеров (для проверки победа/поражение и т.п.)."""
    return [
        child.accent_colour
        for child in view.walk_children()
        if isinstance(child, discord.ui.Container)
    ]
