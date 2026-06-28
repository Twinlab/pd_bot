"""Тесты единого UI-слоя: палитра, фабрика CV2-карточек и ассерт-хелперы."""

import discord

from utils.ui import colors, image_card, link_button, link_row
from utils.ui import testing as ui_testing


def test_palette_values_are_colours() -> None:
    """Все статусные цвета палитры — это discord.Colour."""
    for value in (colors.NEUTRAL, colors.SUCCESS, colors.ERROR, colors.INFO, colors.WARNING):
        assert isinstance(value, discord.Colour)


def test_result_accent_switches_on_outcome() -> None:
    """Победа — зелёный (SUCCESS), поражение — красный (ERROR)."""
    assert colors.result_accent(True) == colors.SUCCESS
    assert colors.result_accent(False) == colors.ERROR


def test_link_button_is_link_style() -> None:
    """link_button создаёт кнопку-ссылку с переданными label/url."""
    btn = link_button("FACEIT", "https://faceit.com")
    assert btn.style is discord.ButtonStyle.link
    assert btn.label == "FACEIT"
    assert btn.url == "https://faceit.com"


def test_link_row_collects_all_pairs() -> None:
    """link_row разворачивает пары (label, url) в ActionRow с кнопками-ссылками."""
    row = link_row([("A", "https://a.com"), ("B", "https://b.com")])
    labels = [(c.label, c.url) for c in row.children if isinstance(c, discord.ui.Button)]
    assert labels == [("A", "https://a.com"), ("B", "https://b.com")]


def test_image_card_full_structure() -> None:
    """image_card раскладывает текст-сверху → картинку → текст-снизу → ссылки."""
    view = image_card(
        media="attachment://card.png",
        accent=colors.result_accent(True),
        text_above=["# Заголовок", "### подзаголовок"],
        text_below=["мета"],
        links=[("Профиль", "https://example.com")],
        timeout=42,
    )

    assert isinstance(view, discord.ui.LayoutView)
    assert view.timeout == 42
    assert ui_testing.text_blocks(view) == ["# Заголовок", "### подзаголовок", "мета"]
    assert ui_testing.media_sources(view) == ["attachment://card.png"]
    assert ui_testing.link_buttons(view) == [("Профиль", "https://example.com")]
    assert ui_testing.accent_colours(view) == [colors.SUCCESS]


def test_image_card_minimal_only_media() -> None:
    """Без текста и ссылок остаётся одна картинка без акцента."""
    view = image_card(media="https://cdn.example/img.png")
    assert ui_testing.text_blocks(view) == []
    assert ui_testing.link_buttons(view) == []
    assert ui_testing.media_sources(view) == ["https://cdn.example/img.png"]
    assert ui_testing.accent_colours(view) == [None]
