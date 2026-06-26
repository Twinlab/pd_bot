"""Тесты рендера карточек матчей (utils/match_card).

Рендер не должен падать ни с картинками, ни без них, и обязан отдавать валидный PNG.
Сетевые загрузки не трогаем — байты «картинок» генерим локально через Pillow.
"""

from dataclasses import replace
from io import BytesIO

from PIL import Image

from utils.match_card import (
    CsCardData,
    DotaCardData,
    ItemImage,
    item_image_url,
    load_map_image,
    render_cs_card,
    render_dota_card,
)
from utils.match_card.render import _circle, _cover, _fallback_avatar

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _fake_image(size: tuple[int, int] = (64, 64), color: str = "purple") -> bytes:
    buf = BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _cs_data(**overrides) -> CsCardData:
    base = CsCardData(
        verdict="красава разъебал",
        is_victory=True,
        nickname="mONESY",
        level="10",
        elo="3949",
        player_score=13,
        opp_score=4,
        rating_str="1.99",
        rating_is_good=True,
        kda_str="24/10/4",
        kd_str="2.40",
        adr_str="138",
        hs_percent=42,
        kr_str="0.83",
        mvp_str="4",
        entry_str="6/14",
        clutch_str="3",
        util_str="412",
        recent_wins=11,
        recent_losses=9,
        recent_results=[True, True, False, True, False, True, True, False, True, True],
        date_str="18.06.2026",
        duration_str="25:25",
        avg_lobby_lvl="10.0",
    )
    return replace(base, **overrides)


def _dota_data(**overrides) -> DotaCardData:
    base = DotaCardData(
        verdict="заруинил пидорас",
        is_victory=False,
        player_name="Twinlab",
        role="Mid",
        game_mode="Turbo",
        rank="Archon I",
        kda_value_str="13.00",
        kda_str="6/1/7",
        hero_damage="26 286",
        networth="32 886",
        gpm="1261",
        xpm="2168",
        daily_wl="0-0",
        weekly_wl="0-0",
        date_str="05.09.2024",
        duration_str="25:39",
    )
    return replace(base, **overrides)


class TestRenderCsCard:
    def test_returns_png_without_images(self):
        out = render_cs_card(_cs_data(avatar=None, map_bg=None))
        assert out[:8] == _PNG_MAGIC

    def test_returns_png_with_images(self):
        out = render_cs_card(_cs_data(avatar=_fake_image(), map_bg=_fake_image((400, 400))))
        assert out[:8] == _PNG_MAGIC

    def test_defeat_renders(self):
        out = render_cs_card(_cs_data(is_victory=False, rating_is_good=False, avg_lobby_lvl=None))
        assert out[:8] == _PNG_MAGIC

    def test_broken_image_bytes_do_not_crash(self):
        out = render_cs_card(_cs_data(avatar=b"not-an-image", map_bg=b"junk"))
        assert out[:8] == _PNG_MAGIC

    def test_empty_recent_results(self):
        out = render_cs_card(_cs_data(recent_results=[]))
        assert out[:8] == _PNG_MAGIC


class TestRenderDotaCard:
    def test_returns_png_without_images(self):
        out = render_dota_card(_dota_data(items=[], neutral=None, hero_bg=None))
        assert out[:8] == _PNG_MAGIC

    def test_returns_png_with_items_and_hero(self):
        items = [ItemImage(f"item{i}", _fake_image()) for i in range(6)]
        neutral = ItemImage("Ninja Gear", _fake_image())
        out = render_dota_card(
            _dota_data(items=items, neutral=neutral, hero_bg=_fake_image((500, 280)))
        )
        assert out[:8] == _PNG_MAGIC

    def test_partial_and_broken_items(self):
        items = [ItemImage("ok", _fake_image()), ItemImage("", None), ItemImage("bad", b"junk")]
        out = render_dota_card(_dota_data(items=items, neutral=None, hero_bg=None))
        assert out[:8] == _PNG_MAGIC


class TestHelpers:
    def test_item_image_url_strips_prefix(self):
        url = item_image_url("item_blink")
        assert url.endswith("/items/blink.png")
        assert url.startswith("https://")

    def test_load_map_image_missing_returns_none(self):
        assert load_map_image("definitely-not-a-real-map") is None

    def test_cover_matches_box(self):
        out = _cover(Image.new("RGBA", (200, 100), "red"), 80, 80)
        assert out.size == (80, 80)

    def test_circle_returns_rgba(self):
        circ = _circle(_fake_image((128, 128)), 100)
        assert circ is not None
        assert circ.size == (100, 100)
        assert circ.mode == "RGBA"

    def test_circle_none_on_broken_bytes(self):
        assert _circle(b"junk", 100) is None

    def test_fallback_avatar_letter(self):
        av = _fallback_avatar("mONESY", 120)
        assert av.size == (120, 120)
        assert av.mode == "RGBA"

    def test_fallback_avatar_empty_label(self):
        av = _fallback_avatar("   ", 80)
        assert av.size == (80, 80)
