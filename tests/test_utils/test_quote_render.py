"""Проверки реального WebP-рендера цитат без Discord, сети и runtime-файлов."""

import io
import struct
import zlib
from dataclasses import asdict, replace
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from PIL import Image

from utils.quotes import render
from utils.quotes.render import QuoteCard, render_quote_card


@pytest.fixture
def card() -> QuoteCard:
    """Короткая русская цитата с обычной подписью."""
    return QuoteCard(
        text="Ещё одну — и спать.",
        display_name="Капитан Очевидность",
        username="captain",
        created_at=datetime(2026, 10, 5, 21, 30, tzinfo=UTC),
        channel_name="общий",
    )


def avatar_bytes() -> bytes:
    """Создаёт проверочный аватар целиком в памяти."""
    image = Image.effect_noise((384, 384), 70).convert("RGB")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def png_header(width: int, height: int) -> bytes:
    """PNG с размерами в заголовке, который нельзя декодировать в пиксели."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


def test_webp_dimensions_budget_and_input_immutability(
    card: QuoteCard, tmp_path, monkeypatch
) -> None:
    """Рендер возвращает ограниченные байты, не меняет данные и не создаёт файлы."""
    before = asdict(card)
    avatar = avatar_bytes()
    original = bytes(avatar)
    monkeypatch.chdir(tmp_path)
    encoded = render_quote_card(card, avatar)
    assert 0 < len(encoded) <= 262144
    with Image.open(io.BytesIO(encoded)) as image:
        image.load()
        assert image.format == "WEBP"
        assert image.width == 1200
        assert 640 <= image.height <= 1200
        assert image.mode == "RGB"
    assert asdict(card) == before
    assert avatar == original
    assert list(tmp_path.iterdir()) == []


def test_avatar_fallback_is_deterministic(card: QuoteCard) -> None:
    """Битые/отсутствующие аватары дают те же инициалы, а не падение карточки."""
    expected = render_quote_card(card)
    assert render_quote_card(card, b"not an image") == expected
    assert render_quote_card(card, b"") == expected
    assert render_quote_card(card) == expected
    assert render_quote_card(card, avatar_bytes()) != expected


@pytest.mark.parametrize("size", [(4096, 4096), (100000, 100000)])
def test_image_bomb_is_rejected_before_pixel_decode(card: QuoteCard, size: tuple[int, int]) -> None:
    """Большой заголовок не заставляет выделять память под изображение."""
    assert render_quote_card(card, png_header(*size)) == render_quote_card(card)


def test_oversized_avatar_is_not_opened(card: QuoteCard) -> None:
    """Лимит bytes проверяется ещё до запуска декодера."""
    oversized = b"x" * (2 * 1024 * 1024 + 1)
    with patch.object(render.Image, "open", side_effect=AssertionError("must not decode")):
        encoded = render_quote_card(card, oversized)
    assert encoded.startswith(b"RIFF")


def test_cyrillic_multiline_text_and_metadata_are_drawn_without_truncation(card: QuoteCard) -> None:
    """Текст переносится целиком; дата показывается по московскому времени."""
    text = "План на вечер:\nодна катка\nкрасивая победа\nи сразу спать.\n\nПлан был хороший."
    with patch.object(render, "_line", wraps=render._line) as draw_line:
        encoded = render_quote_card(replace(card, text=text))
    drawn = [call.args[2] for call in draw_line.call_args_list]
    body = " ".join(line for line in drawn if line not in (drawn[0], drawn[-2], drawn[-1]))
    assert " ".join(text.split()) == " ".join(body.split())
    assert "06.10.2026" in drawn[0]
    assert "#общий" in drawn[0]
    assert "Капитан Очевидность" in drawn[-2]
    assert "@captain" in drawn[-1]
    assert (
        render._display_text("Йёжик, съешь ещё этих мягких булок…")
        == "Йёжик, съешь ещё этих мягких булок…"
    )
    assert len(encoded) < 262144


def test_long_quote_uses_bounded_taller_card(card: QuoteCard) -> None:
    """Для длинной цитаты растёт высота, но весь текст остаётся на карточке."""
    text = "Мы договорились сыграть одну катку и сразу пойти спать. " * 9
    with patch.object(render, "_line", wraps=render._line) as draw_line:
        encoded = render_quote_card(replace(card, text=text))
    lines = [call.args[2] for call in draw_line.call_args_list][1:-2]
    assert " ".join(" ".join(lines).split()) == text.strip()
    with Image.open(io.BytesIO(encoded)) as image:
        assert image.width == 1200
        assert 640 < image.height <= 1200


def test_known_emoji_use_assets_and_unknown_emoji_have_explicit_tokens(card: QuoteCard) -> None:
    """Известные emoji сохраняются, неизвестные и ZWJ не превращаются в квадраты."""
    text = "Катка 🎮🏆⭐ и огонь 🔥. Разработчица 👩\u200d💻, флаг 🇷🇺."
    shown = render._display_text(text)
    assert "🎮🏆⭐" in shown
    assert "[fire]" in shown
    assert "[woman / personal computer]" in shown
    assert "[flag RU]" in shown
    assert "\u200d" not in shown
    assert "🔥" not in shown
    encoded = render_quote_card(replace(card, text=text))
    assert len(encoded) <= 262144


def test_variations_skin_tones_and_controls_are_not_silently_lost() -> None:
    """Составные emoji и невидимые управляющие последовательности имеют явное представление."""
    assert render._display_text("🎙️") == "🎙"
    assert render._display_text("👍🏽") == "[thumbs up / type-4]"
    assert render._display_text("слово\u202eтекст") == "слово[U+202E]текст"
    assert render._display_text("中") == "[U+4E2D]"
    assert render._display_text("x\x00y") == "x[U+0000]y"


@pytest.mark.parametrize("text", ["", " \n\t ", "я" * 1001, "W" * 1000, "а\u0301" + "\u0301" * 100])
def test_invalid_or_unreadable_text_is_rejected_not_truncated(card: QuoteCard, text: str) -> None:
    """Непомещающийся текст не выдаётся за полную цитату."""
    with pytest.raises(ValueError):
        render_quote_card(replace(card, text=text))


def test_custom_byte_budget_and_impossible_budget(card: QuoteCard) -> None:
    """Лимит применяется к реально закодированному файлу, а не к оценке размера."""
    assert len(render_quote_card(card, max_bytes=32 * 1024)) <= 32 * 1024
    with pytest.raises(ValueError, match="размер файла"):
        render_quote_card(card, max_bytes=32)


@pytest.mark.parametrize("budget", [0, -1, True, 1024 * 1024 + 1])
def test_invalid_byte_budget_is_rejected(card: QuoteCard, budget: int) -> None:
    with pytest.raises(ValueError, match="Лимит"):
        render_quote_card(card, max_bytes=budget)


def test_metadata_requires_timezone_and_reasonable_length(card: QuoteCard) -> None:
    with pytest.raises(ValueError, match="часовой пояс"):
        render_quote_card(replace(card, created_at=card.created_at.replace(tzinfo=None)))
    with pytest.raises(ValueError, match="Подпись"):
        render_quote_card(replace(card, display_name="x" * 201))
