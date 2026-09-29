"""Расчёты процентов и геометрия рабочего рендера monthly wrapped."""

from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from utils.wrapped.builder import NamedValue, Nomination, ServerWrapped
from utils.wrapped.monthly_render import (
    _CardData, _Metric, _Row, _change, _clean, _fit, _render_layout, _value,
)
from utils.wrapped.render import render_server_card


@pytest.mark.parametrize("current,previous,ready,expected", [
    (18420, 15000, True, "+22,8%"),
    (48600, 54000, True, "−10,0%"),
    (0, 50, True, "−100,0%"),
    (1, 0, True, "Ранее — 0"),
    (0, 0, True, "Без изменений"),
    (1, 1, True, "0%"),
    (10001, 10000, True, "Рост < 0,1%"),
    (9999, 10000, True, "Снижение < 0,1%"),
    (1, None, True, "Нет сравнения"),
    (1, 0, False, "Нет сравнения"),
    (None, 1, True, "Данные недоступны"),
])
def test_percentage(current, previous, ready, expected) -> None:
    assert _change(_Metric("", current, previous, comparison_ready=ready)) == expected


def test_time_rounding_does_not_affect_percentage() -> None:
    assert _value(59, True) == "< 1 мин"
    assert _value(0, True) == "0 мин"
    assert _value(119, True) == "1 мин"
    assert _change(_Metric("", 119, 61, True, True)) == "+95,1%"


def test_names_and_unsupported_glyphs_remain_safe() -> None:
    assert _clean("Nick\nName\u202e") == "Nick Name"
    assert "[U+" in _clean("🦄")
    name, font = _fit("Очень длинное имя " * 20, 160, 23, 21, True)
    assert name.endswith("…")
    assert font.getlength(name) <= 160


def test_layout_handles_extremes_without_overlapping_text() -> None:
    metrics = (
        _Metric("Сообщения", 2**63-1, 1, comparison_ready=True),
        _Metric("Войс", 1, 0, True, True),
        _Metric("Игры", 0, 100, True, True),
        _Metric("Активные участники", 10001, 10000, comparison_ready=True),
    )
    rows = tuple(_Row("Длинное имя " * 30, 999999999 + i) for i in range(5))
    data = _CardData("Сентябрь", 2026, metrics, rows, rows, rows,
                     (("Разнообразие игр", "Участник " * 30, "100 игр"),))
    for variant in (data, replace(data, messages=(), voice=(), games=(), nominations=())):
        canvas = _render_layout(variant)
        for i, a in enumerate(canvas.boxes):
            for b in canvas.boxes[i+1:]:
                assert not (min(a[2], b[2]) > max(a[0], b[0])
                            and min(a[3], b[3]) > max(a[1], b[1]))


def test_actual_entrypoint_uses_new_design_and_data(tmp_path) -> None:
    summary = ServerWrapped(
        period_label="Август 2026", scope="monthly", total_messages=18420,
        total_voice_seconds=1944000, total_game_seconds=2916000, active_users=42,
        previous={"messages": 15000, "voice": 1620000, "games": 3240000, "users": 38},
        top_messages=[NamedValue(1, 3240), NamedValue(2, 2810), NamedValue(3, 1960)],
        top_voice=[NamedValue(2, 374400), NamedValue(4, 306000), NamedValue(1, 262800)],
        top_games=[("Dota 2", 1584000), ("Counter-Strike 2", 684000), ("Minecraft", 360000),
                   ("Genshin Impact", 180000), ("Deadlock", 60000)],
        nominations=[Nomination("", "Разнообразие игр", 2, "8 игр"),
                     Nomination("", "Сообщение месяца", 1, "47 реакций"),
                     Nomination("", "Геймер", 4, "9 600 мин"),
                     Nomination("", "По реакциям", 3, "342 реакции")],
    )
    names = {1: "Котобус", 2: "mango", 3: "Пельмень", 4: "Сова"}
    png = render_server_card(summary, names.__getitem__)
    im = Image.open(BytesIO(png))
    assert im.size[0] == 1200
    assert im.getpixel((0, 0)) == (255, 66, 75)
    (tmp_path / "monthly.png").write_bytes(png)


@pytest.mark.parametrize("value", [-1, True, 1.2, 2**63])
def test_bad_values_rejected(value) -> None:
    with pytest.raises(ValueError):
        _value(value)
