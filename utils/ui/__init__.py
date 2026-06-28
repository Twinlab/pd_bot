"""Общий UI-слой бота: палитра цветов и фабрики Components V2.

* :mod:`utils.ui.colors` — единая палитра (нейтраль из тем 2.6 + статусные цвета).
* :mod:`utils.ui.components` — ``image_card`` / ``link_row`` для CV2-карточек.
* :mod:`utils.ui.testing` — ассерт-хелперы для тестов CV2.
"""

from __future__ import annotations

from . import colors
from .components import image_card, link_button, link_row

__all__ = ["colors", "image_card", "link_button", "link_row"]
