"""Тесты рендера wrapped-карточек (проверяем, что выходит валидный PNG)."""

from utils.wrapped.builder import NamedValue, Nomination, PersonalWrapped, ServerWrapped
from utils.wrapped.render import render_personal_card, render_server_card

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def test_render_server_card_returns_png():
    summary = ServerWrapped(
        period_label="Май 2026",
        scope="monthly",
        total_messages=1500,
        total_voice_seconds=36000,
        total_game_seconds=72000,
        active_users=12,
        top_messages=[NamedValue(1, 500), NamedValue(2, 300)],
        top_voice=[NamedValue(2, 18000), NamedValue(1, 9000)],
        top_games=[("Dota 2", 40000), ("CS2", 20000)],
        nominations=[Nomination("💬", "Болтун", 1, "500 сообщ.")],
        footnote="тест",
    )
    png = render_server_card(summary, lambda uid: f"User{uid}")
    assert png.startswith(_PNG_SIGNATURE)
    assert len(png) > 1000


def test_render_server_card_empty():
    summary = ServerWrapped(
        period_label="2026 год",
        scope="yearly",
        total_messages=0,
        total_voice_seconds=0,
        total_game_seconds=0,
        active_users=0,
    )
    png = render_server_card(summary, lambda uid: f"User{uid}")
    assert png.startswith(_PNG_SIGNATURE)


def test_render_personal_card_returns_png():
    personal = PersonalWrapped(
        user_id=1,
        period_label="2026 год",
        messages=1234,
        voice_seconds=54000,
        game_seconds=90000,
        reactions_received=88,
        favorite_game="Dota 2",
        top_games=[("Dota 2", 60000), ("CS2", 30000)],
        message_rank=3,
        voice_rank=1,
        total_users=20,
        footnote="тест",
    )
    png = render_personal_card(personal, "Тестовый Юзер")
    assert png.startswith(_PNG_SIGNATURE)
    assert len(png) > 1000
