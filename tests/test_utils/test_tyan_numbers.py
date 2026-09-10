"""Проверки распределения возраста и веса, границ и дневных снимков /tyan."""

import random
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from utils.tyan.catalog import load_catalog
from utils.tyan.config import TyanConfig
from utils.tyan.generator import generate_roll
from utils.tyan.simulation import build_simulation

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def roll(config, rng, history=()):
    return generate_roll(
        load_catalog(), config, user_id=1, now=NOW, history=history, rng=rng
    )


@pytest.fixture(scope="module")
def samples():
    config = TyanConfig(mother_chance=0, none_chance=0)
    rng = random.Random(20260911)
    return [roll(config, rng) for _ in range(10000)]


def test_age_distribution_and_all_endpoints(samples):
    ages = Counter(0 if row.age <= 40 else 1 if row.age <= 55 else 2 for row in samples)
    for group, expected in enumerate((0.85, 0.10, 0.05)):
        assert ages[group] / len(samples) == pytest.approx(expected, abs=0.015)
    assert {18, 40, 41, 55, 56, 80} <= {row.age for row in samples}


def test_weight_distribution_and_height_limits(samples):
    groups = Counter()
    for row in samples:
        assert 140 <= row.height <= 200
        lower = max(30, (row.height - 79) // 2)
        assert lower <= row.weight <= 120
        groups[0 if row.weight <= lower + 25 else 1 if row.weight <= lower + 50 else 2] += 1
    for group, expected in enumerate((0.60, 0.30, 0.10)):
        assert groups[group] / len(samples) == pytest.approx(expected, abs=0.015)
    assert {row.height for row in samples} == set(range(140, 201))
    assert min(row.weight for row in samples) == 30
    assert max(row.weight for row in samples) == 120


@pytest.mark.parametrize("height,ranges", [
    (140, ((30, 55), (56, 80), (81, 120))),
    (170, ((45, 70), (71, 95), (96, 120))),
    (199, ((60, 85), (86, 110), (111, 120))),
    (200, ((60, 85), (86, 110), (111, 120))),
])
def test_each_weight_group_reaches_expected_bounds(height, ranges):
    for group, (low, high) in enumerate(ranges):
        config = TyanConfig(
            height_min=height, height_max=height,
            weight_weights=tuple(int(index == group) for index in range(3)),
            mother_chance=0, none_chance=0,
        )
        assert config.weight_ranges(height) == ranges
        rng = random.Random(42)
        weights = {roll(config, rng).weight for _ in range(500)}
        assert weights == set(range(low, high + 1))


@pytest.mark.parametrize("group,low,high", [(0, 18, 40), (1, 41, 55), (2, 56, 80)])
def test_age_weights_can_select_each_group(group, low, high):
    config = TyanConfig(
        age_weights=tuple(int(index == group) for index in range(3)),
        mother_chance=0, none_chance=0,
    )
    rng = random.Random(42)
    ages = {roll(config, rng).age for _ in range(500)}
    assert ages == set(range(low, high + 1))


@pytest.mark.parametrize("age,height,weight", [(66, 200, 60), (18, 140, 120)])
def test_narrow_config_preserves_allowed_edge_combinations(age, height, weight):
    config = TyanConfig(
        age_min=age, age_max=age, height_min=height, height_max=height,
        weight_min=weight, weight_max=weight, mother_chance=0, none_chance=0,
    )
    row = roll(config, random.Random(42))
    assert (row.age, row.height, row.weight) == (age, height, weight)
    assert f"{age}-летняя {height}/{weight}" in row.text


@pytest.mark.parametrize("kwargs", [
    {"age_weights": (0, 0, 0)}, {"age_weights": (-1, 1, 1)},
    {"age_weights": (float("nan"), 1, 1)},
    {"age_min": 56, "age_weights": (1, 0, 0)},
    {"weight_weights": (0, 0, 0)}, {"weight_weights": (1, float("inf"), 1)},
    {"weight_weights": (1, float("nan"), 1)},
    {"height_min": 200, "weight_max": 30},
    {"weight_max": 80, "weight_weights": (0, 0, 1)},
])
def test_impossible_ranges_and_probabilities_fail_early(kwargs):
    with pytest.raises(ValueError):
        TyanConfig(**kwargs)


def test_saved_result_survives_number_balance_change():
    config = TyanConfig(mother_chance=0, none_chance=0)
    saved = replace(
        roll(config, random.Random(42)),
        age=75, height=200, weight=30, text="сохранённая 75-летняя 200/30",
    )
    assert roll(config, random.Random(43), history=[saved]) is saved


def test_simulation_reports_real_counts_and_unselected_examples():
    report = build_simulation(count=50, seed=1)
    assert "Выдач: 50; seed: 1" in report
    assert "Нарушений границ возраста/роста/веса: 0." in report
    assert "| Возраст |" in report and "| Вес |" in report
    assert "15. грац, тебе досталась" in report
    assert report == build_simulation(count=50, seed=1)
    with pytest.raises(ValueError):
        build_simulation(count=0)
