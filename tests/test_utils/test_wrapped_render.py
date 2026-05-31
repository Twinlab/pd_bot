"""Тесты рендера wrapped-карточек (проверяем, что выходит валидный PNG)."""

from io import BytesIO
from pathlib import Path

from PIL import Image

from utils.wrapped import render
from utils.wrapped.builder import NamedValue, Nomination, PersonalWrapped, ServerWrapped
from utils.wrapped.render import render_personal_card, render_server_card

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Куда складывать превью для глазного контроля (downloads/ в .gitignore).
_PREVIEW_DIR = Path(__file__).resolve().parents[2] / "downloads"


def _fake_avatar(color: tuple[int, int, int] = (90, 120, 200)) -> bytes:
    """Маленький валидный PNG как имитация аватара пользователя."""
    buf = BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


def _write_preview(name: str, png: bytes) -> None:
    try:
        _PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        (_PREVIEW_DIR / name).write_bytes(png)
    except OSError:
        pass


def _full_server() -> ServerWrapped:
    return ServerWrapped(
        period_label="Май 2026",
        scope="monthly",
        total_messages=15243,
        total_voice_seconds=486000,
        total_game_seconds=720000,
        active_users=42,
        top_messages=[NamedValue(1, 5000), NamedValue(2, 3200), NamedValue(3, 1800)],
        top_voice=[NamedValue(2, 180000), NamedValue(1, 90000), NamedValue(4, 45000)],
        top_games=[("Dota 2", 320000), ("Counter-Strike 2", 210000), ("Marvel Rivals", 120000)],
        nominations=[
            Nomination("💬", "По сообщениям", 1, "5000 сообщ."),
            Nomination("🎙️", "По войсу", 2, "50ч"),
            Nomination("🎮", "Геймер", 3, "61ч 20м"),
            Nomination("⭐", "По реакциям", 4, "342 реакц."),
        ],
        footnote="PD Bot · данные собираются с 2026-06-01",
    )


def test_render_server_card_returns_png():
    png = render_server_card(_full_server(), lambda uid: f"User{uid}")
    assert png.startswith(_PNG_SIGNATURE)
    assert len(png) > 1000
    _write_preview("wrapped_preview_server.png", png)


def test_render_server_card_with_avatars():
    summary = _full_server()
    avatars = {nom.user_id: _fake_avatar() for nom in summary.nominations if nom.user_id}
    png = render_server_card(summary, lambda uid: f"User{uid}", avatars)
    assert png.startswith(_PNG_SIGNATURE)
    _write_preview("wrapped_preview_server_avatars.png", png)


def test_render_server_card_empty():
    # «Первый месяц»: сообщения/войс ещё не накопились (data_since недавно),
    # а игры уже есть из давно работающего модуля активности.
    summary = ServerWrapped(
        period_label="Июнь 2026",
        scope="monthly",
        total_messages=0,
        total_voice_seconds=0,
        total_game_seconds=200 * 3600,
        active_users=22,
        top_games=[("Dota 2", 320000), ("Counter-Strike 2", 210000), ("Marvel Rivals", 120000)],
        nominations=[
            Nomination("🎮", "Геймер", 3, "61ч 20м"),
            Nomination("⭐", "По реакциям", 4, "342 реакц."),
        ],
        footnote="PD Bot · данные собираются с 2026-06-01",
    )
    png = render_server_card(summary, lambda uid: f"User{uid}")
    assert png.startswith(_PNG_SIGNATURE)
    _write_preview("wrapped_preview_empty.png", png)


def test_render_personal_card_returns_png():
    personal = PersonalWrapped(
        user_id=1,
        period_label="2026 год",
        messages=1234,
        voice_seconds=54000,
        game_seconds=90000,
        reactions_received=88,
        favorite_game="Dota 2",
        top_games=[("Dota 2", 60000), ("CS2", 30000), ("Marvel Rivals", 12000)],
        message_rank=3,
        voice_rank=1,
        reaction_rank=5,
        reaction_total=40,
        total_users=42,
        footnote="PD Bot · Personal Wrapped",
    )
    png = render_personal_card(personal, "Тестовый Юзер", _fake_avatar((200, 90, 140)))
    assert png.startswith(_PNG_SIGNATURE)
    assert len(png) > 1000
    _write_preview("wrapped_preview_personal.png", png)


def test_icon_fallback_for_unknown_emoji():
    """Неизвестный эмодзи не должен ломать рендер — иконка просто пропускается."""
    assert render._icon_array("🛸") is None


def test_render_survives_missing_assets(monkeypatch):
    """Если ассеты эмодзи недоступны, рендер всё равно отдаёт валидный PNG."""
    monkeypatch.setattr(render, "_icon_cache", {})
    monkeypatch.setattr(render, "_EMOJI_DIR", Path("/nonexistent/emoji"))
    png = render_server_card(_full_server(), lambda uid: f"User{uid}")
    assert png.startswith(_PNG_SIGNATURE)
