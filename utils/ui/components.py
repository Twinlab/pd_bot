"""Фабрики Components V2 — единая сборка карточек, чтобы не дублировать вёрстку.

``image_card`` собирает типовую CV2-карточку «картинка + опциональный текст
сверху/снизу + ряд ссылок» в одном ``LayoutView`` с акцент-полосой контейнера.
До этого один и тот же набор ``Container`` + ``MediaGallery`` + ``ActionRow``
повторялся в карточках матчей (Dota/CS), уведомлениях Twitch и постах аниме.
"""

from __future__ import annotations

from collections.abc import Sequence

import discord


def link_button(label: str, url: str) -> discord.ui.Button:
    """Создаёт кнопку-ссылку (стиль ``link``, без callback)."""
    return discord.ui.Button(style=discord.ButtonStyle.link, label=label, url=url)


def link_row(links: Sequence[tuple[str, str]]) -> discord.ui.ActionRow:
    """Собирает ``ActionRow`` из пар ``(label, url)``."""
    return discord.ui.ActionRow(*(link_button(label, url) for label, url in links))


def image_card(
    *,
    media: str,
    accent: discord.Colour | int | None = None,
    text_above: Sequence[str] | None = None,
    text_below: Sequence[str] | None = None,
    links: Sequence[tuple[str, str]] | None = None,
    timeout: float | None = None,
) -> discord.ui.LayoutView:
    """Собирает CV2-карточку: текст сверху → картинка → текст снизу → ссылки.

    Args:
        media: Источник картинки — URL или ``attachment://<filename>`` для файла,
            приложенного к тому же сообщению.
        accent: Цвет акцентной полосы контейнера (``Colour`` или int). ``None`` —
            без полосы.
        text_above: Блоки ``TextDisplay`` над картинкой (markdown), сверху вниз.
        text_below: Блоки ``TextDisplay`` под картинкой (markdown), сверху вниз.
        links: Пары ``(label, url)`` для ряда кнопок-ссылок под карточкой.
        timeout: Таймаут ``LayoutView`` в секундах (``None`` — без таймаута).

    Returns:
        Готовый ``LayoutView`` с единственным контейнером.
    """
    container: discord.ui.Container = discord.ui.Container(accent_colour=accent)
    for block in text_above or ():
        container.add_item(discord.ui.TextDisplay(block))
    container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(media=media)))
    for block in text_below or ():
        container.add_item(discord.ui.TextDisplay(block))
    if links:
        container.add_item(link_row(links))

    view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=timeout)
    view.add_item(container)
    return view
