"""Проверки ежедневной выдачи, редких событий и ограничений словаря."""

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from utils.tyan.catalog import Catalog, Word, load_catalog
from utils.tyan.config import TyanConfig
from utils.tyan.generator import generate_roll
from utils.tyan.presentation import build_tyan_card
from utils.tyan.types import Roll

NOW = datetime(2026, 9, 10, 20, 59, tzinfo=UTC)


def catalog(size=100):
    def pool(prefix):
        return tuple(
            Word(id=f"{prefix}_{i}", text=f"{prefix}{i}", tone=(
                "positive" if i % 3 == 0 else "neutral" if i % 3 == 1 else "negative"
            )) for i in range(size)
        )
    return Catalog(adjectives=pool("adj"), archetypes=pool("type"), traits=pool("trait"))


def generate(config=None, **kwargs):
    options = dict(user_id=1, now=NOW, history=[], rng=random.Random(42))
    options.update(kwargs)
    return generate_roll(catalog(), config or TyanConfig(mother_chance=0, none_chance=0), **options)


def test_same_moscow_day_returns_snapshot_even_after_catalog_changes():
    original = generate()
    changed = replace(original, text="сохранённый текст удалённого элемента")
    result = generate(now=NOW + timedelta(seconds=30), history=[changed])
    assert result is changed


def test_moscow_midnight_changes_day_not_server_utc_date():
    first = generate()
    second = generate(now=NOW + timedelta(minutes=2), history=[first])
    assert first.day.isoformat() == "2026-09-10"
    assert second.day.isoformat() == "2026-09-11"
    assert second.archetype_id != first.archetype_id


def test_naive_time_is_rejected():
    with pytest.raises(ValueError, match="пояс"):
        generate(now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("field,min_value,max_value", [
    ("age", 18, 80), ("height", 140, 200), ("weight", 30, 120),
])
def test_numbers_reach_both_extremes_independently(field, min_value, max_value):
    rows = [generate(rng=random.Random(seed)) for seed in range(1000)]
    values = {getattr(row, field) for row in rows}
    assert min(values) == min_value
    assert max(values) == max_value


def test_implausible_measurements_are_not_corrected():
    config = TyanConfig(age_min=66, age_max=66, height_min=190, height_max=190,
                        weight_min=34, weight_max=34, mother_chance=0, none_chance=0)
    row = generate(config)
    assert (row.age, row.height, row.weight) == (66, 190, 34)
    assert "66-летняя 190/34" in row.text


@pytest.mark.parametrize("weights,expected", [
    ((1, 0, 0), 1), ((0, 1, 0), 2), ((0, 0, 1), 3),
])
def test_one_to_three_text_elements(weights, expected):
    cfg = TyanConfig(part_weights=weights, positive_chance=0, mother_chance=0, none_chance=0)
    for seed in range(20):
        row = generate(cfg, rng=random.Random(seed))
        assert sum(value is not None for value in (
            row.adjective_id, row.archetype_id, row.trait_id
        )) == expected


def test_positive_roll_has_only_positive_modifiers_and_no_negative_archetype():
    words = catalog()
    lookup = {word.id: word for pool in (
        words.adjectives, words.archetypes, words.traits
    ) for word in pool}
    cfg = TyanConfig(positive_chance=1, mother_chance=0, none_chance=0)
    for seed in range(100):
        row = generate(cfg, rng=random.Random(seed))
        assert lookup[row.adjective_id].tone == "positive"
        if row.trait_id is not None:
            assert lookup[row.trait_id].tone == "positive"
        assert lookup[row.archetype_id].tone != "negative"


def test_type_is_not_repeated_in_fifteen_daily_results():
    history = []
    for user_id in range(1, 16):
        history.append(generate(user_id=user_id, history=history))
    assert len({row.archetype_id for row in history}) == 15


def test_personal_type_cooldown_is_applied():
    cfg = TyanConfig(positive_chance=0, mother_chance=0, none_chance=0)
    history = []
    for day in range(60):
        history.append(generate(cfg, now=NOW + timedelta(days=day), history=history))
    assert len({row.archetype_id for row in history}) == 60


def test_adjective_archetype_pair_is_not_repeated_across_users():
    words = catalog()
    words = replace(words, archetypes=(words.archetypes[0],))
    cfg = TyanConfig(part_weights=(0, 0, 1), positive_chance=0,
                     mother_chance=0, none_chance=0)
    first = generate_roll(words, cfg, user_id=1, now=NOW, history=[], rng=random.Random(1))
    second = generate_roll(words, cfg, user_id=2, now=NOW + timedelta(days=1),
                           history=[first], rng=random.Random(1))
    assert first.adjective_id != second.adjective_id
    assert first.trait_id != second.trait_id


def test_small_exhausted_catalog_still_returns_a_result():
    words = catalog(size=1)
    cfg = TyanConfig(positive_chance=1, mother_chance=0, none_chance=0)
    first = generate_roll(words, cfg, user_id=1, now=NOW, history=[])
    second = generate_roll(words, cfg, user_id=2, now=NOW, history=[first])
    assert second.kind == "normal"


def test_mother_chooses_another_member_and_is_stable_for_the_day():
    cfg = TyanConfig(mother_chance=1, none_chance=0)
    first = generate(cfg, member_ids=[1, 2, 2])
    assert first.kind == "mother"
    assert first.target_user_id == 2
    assert first.text == "тебе досталась мать <@2>"
    assert generate(cfg, history=[first], member_ids=[3]) == first


def test_mother_without_other_members_becomes_normal_not_empty_event():
    row = generate(TyanConfig(mother_chance=1, none_chance=0), member_ids=[1])
    assert row.kind == "normal"
    assert row.target_user_id is None


def test_empty_event_replaces_entire_character():
    row = generate(TyanConfig(mother_chance=0, none_chance=1))
    assert row.kind == "none"
    assert row.text == "тянки не досталось. сегодня дрочишь"
    assert row.age is None and row.archetype_id is None


@pytest.mark.parametrize("event_kind", ["mother", "none"])
def test_global_event_cooldown_survives_other_users_and_kinds(event_kind):
    first = Roll(user_id=2, day=NOW.date(), created_at=NOW,
                 kind=event_kind, text="редкое событие", target_user_id=3)
    cfg = TyanConfig(mother_chance=0, none_chance=1)
    assert generate(cfg, now=NOW + timedelta(days=14, seconds=-1),
                    history=[first]).kind == "normal"
    assert generate(cfg, now=NOW + timedelta(days=14),
                    history=[first]).kind == "none"


@pytest.mark.parametrize("kwargs", [
    {"age_min": 17}, {"age_min": 70, "age_max": 20},
    {"height_min": 200, "height_max": 150}, {"weight_min": 90, "weight_max": 30},
    {"mother_chance": .6, "none_chance": .5}, {"mother_chance": float("nan")},
    {"part_weights": (0, 0, 0)}, {"part_weights": (-1, 1, 1)},
    {"part_weights": (float("nan"), 1, 1)},
])
def test_invalid_settings_fail_early(kwargs):
    with pytest.raises(ValueError):
        TyanConfig(**kwargs)


def test_real_catalog_contains_all_tones_and_loads_once():
    words = load_catalog()
    assert load_catalog() is words
    for pool in (words.adjectives, words.archetypes, words.traits):
        assert {word.tone for word in pool} == {"positive", "neutral", "negative"}


@pytest.mark.parametrize("text", ["@everyone", "abc\ndef", " x", "<@123>"])
def test_catalog_rejects_mentions_and_malformed_text(text):
    with pytest.raises(ValueError):
        Word(id="test_id", text=text, tone="neutral")


def test_card_displays_saved_result_and_daily_reset():
    row = generate()
    card = build_tyan_card(row, display_name="Игрок").to_dict()
    assert card["description"] == row.text
    assert card["author"]["name"] == "Тянка на сегодня · Игрок"
    assert card["footer"]["text"] == "Следующая выдача — в 00:00 МСК"


def test_catalog_rejects_empty_and_duplicate_pools(tmp_path):
    for name in ("adjectives", "archetypes", "traits"):
        (tmp_path / f"{name}.yaml").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="непустым"):
        load_catalog(tmp_path)
    (tmp_path / "adjectives.yaml").write_text(
        "- {id: adj_one, text: одна, tone: positive}\n"
        "- {id: adj_one, text: другая, tone: positive}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Дубли"):
        load_catalog(tmp_path)


def test_recent_negative_family_penalizes_positive_variant():
    from utils.tyan.generator import _choose

    good = Word(id="adj_good", text="скилловая", tone="positive", family="skill")
    bad = Word(id="adj_bad", text="забущенная", tone="negative", family="skill")
    fresh = Word(id="adj_fresh", text="симпотная", tone="positive")
    previous = Roll(user_id=2, day=NOW.date(), created_at=NOW - timedelta(hours=1),
                    kind="normal", text="снимок", adjective_id=bad.id)

    class InspectRandom(random.Random):
        def choices(self, population, weights=None, **kwargs):
            actual = {word.id: weight for word, weight in zip(population, weights)}
            assert actual[good.id] < actual[fresh.id]
            return [fresh]

    assert _choose(
        (good, fresh), "adjective_id", family_pool=(good, bad, fresh),
        user_id=1, now=NOW, history=[previous], cooldown=30,
        pair_cooldown=120, archetype_id=None, rng=InspectRandom(),
    ) == fresh


def test_positive_fallback_never_uses_negative_alternatives():
    words = catalog(size=3)
    cfg = TyanConfig(positive_chance=1, mother_chance=0, none_chance=0)
    rows = []
    for index in range(10):
        rows.append(generate_roll(words, cfg, user_id=1,
                    now=NOW + timedelta(days=index), history=rows))
    assert all(row.adjective_id == "adj_0" and row.trait_id in (None, "trait_0") for row in rows)
    assert all(row.archetype_id != "type_2" for row in rows)


@pytest.mark.parametrize("chance,kind", [(0.00499, "mother"), (0.005, "none"), (0.01, "normal")])
def test_event_probability_boundaries(chance, kind):
    class FirstRoll(random.Random):
        def __init__(self):
            super().__init__(42)
            self.first = True

        def random(self):
            if self.first:
                self.first = False
                return chance
            return super().random()

    row = generate(TyanConfig(), member_ids=[1, 2], rng=FirstRoll())
    assert row.kind == kind


def test_preview_is_reproducible_and_has_thirty_labeled_examples():
    from utils.tyan.preview import build_preview

    text = build_preview()
    assert text == build_preview()
    lines = [line for line in text.splitlines() if line.split(".")[0].isdigit()]
    assert len(lines) == 30
    assert lines[-2] == "29. тебе досталась мать @random-user"
    assert lines[-1] == "30. тянки не досталось. сегодня дрочишь"


@pytest.mark.parametrize("weights,has_suffix", [((1, 0, 0), False), ((0, 1, 0), False), ((0, 0, 1), True)])
def test_positive_roll_keeps_optional_suffix(weights, has_suffix):
    cfg = TyanConfig(positive_chance=1, mother_chance=0, none_chance=0, part_weights=weights)
    for seed in range(20):
        row = generate(cfg, rng=random.Random(seed))
        assert row.adjective_id is not None
        assert (row.trait_id is not None) == has_suffix


@pytest.mark.parametrize("text,joiner,ending", [
    ("с пирсингом", "space", "type0 с пирсингом"),
    ("рот в говне", "comma", "type0, рот в говне"),
    ("но уже замужем", "comma", "type0, но уже замужем"),
])
def test_suffix_punctuation_keeps_one_trait(text, joiner, ending):
    words = replace(catalog(size=1), traits=(Word(
        id="trait_clause", text=text, tone="negative", joiner=joiner,
    ),))
    cfg = TyanConfig(positive_chance=0, mother_chance=0, none_chance=0,
                     part_weights=(0, 0, 1))
    row = generate_roll(words, cfg, user_id=1, now=NOW, history=[], rng=random.Random(1))
    assert row.text.endswith(ending)
    assert row.adjective_id is not None
    assert row.archetype_id is not None
    assert row.trait_id == "trait_clause"


def test_catalog_rejects_unknown_joiner():
    with pytest.raises(ValueError):
        Word(id="trait_bad", text="одна фраза", tone="neutral", joiner="semicolon")



def test_excluded_pair_is_not_restored_when_repeat_history_is_exhausted():
    words = catalog(size=1)
    smart = Word(id="adj_smart", text="умная", tone="positive", avoid_archetypes=("type_0",))
    gentle = Word(id="adj_gentle", text="нежная", tone="positive")
    words = replace(words, adjectives=(smart, gentle))
    cfg = TyanConfig(positive_chance=1, mother_chance=0, none_chance=0,
                     part_weights=(0, 1, 0))
    history = []
    for day in range(5):
        row = generate_roll(words, cfg, user_id=1, now=NOW + timedelta(days=day),
                            history=history, rng=random.Random(day))
        assert row.adjective_id == gentle.id
        history.append(row)


def test_word_excluded_for_one_type_remains_available_for_another():
    words = catalog(size=1)
    smart = Word(id="adj_smart", text="умная", tone="positive", avoid_archetypes=("type_vampire",))
    words = replace(words, adjectives=(smart,))
    row = generate_roll(words, TyanConfig(positive_chance=1, mother_chance=0, none_chance=0),
                        user_id=1, now=NOW, history=[])
    assert row.adjective_id == smart.id
    assert "умная type0" in row.text


@pytest.mark.parametrize("has_alternative", [True, False])
def test_archetype_requiring_modifier_is_not_shown_bare(has_alternative):
    words = catalog(size=1)
    restricted = words.archetypes[0].model_copy(update={"standalone": False})
    types = (restricted,)
    if has_alternative:
        types += (Word(id="type_other", text="няшка", tone="positive"),)
    words = replace(words, archetypes=types)
    row = generate_roll(words, TyanConfig(positive_chance=0, mother_chance=0,
                        none_chance=0, part_weights=(1, 0, 0)),
                        user_id=1, now=NOW, history=[])
    if has_alternative:
        assert row.archetype_id == "type_other"
        assert row.adjective_id is None and row.trait_id is None
    else:
        assert row.archetype_id == restricted.id
        assert row.adjective_id is not None


@pytest.mark.parametrize("target,match", [
    ("type_unknown", "Неизвестные типажи"),
    ("type_0", "Нет положительных прилагательных"),
])
def test_catalog_checks_pair_references_and_positive_coverage(tmp_path, target, match):
    import yaml

    words = catalog(size=3)
    for name in ("adjectives", "archetypes", "traits"):
        entries = [word.model_dump(mode="json") for word in getattr(words, name)]
        if name == "adjectives":
            entries[0]["avoid_archetypes"] = [target]
        (tmp_path / f"{name}.yaml").write_text(
            yaml.safe_dump(entries, allow_unicode=True), encoding="utf-8"
        )
    with pytest.raises(ValueError, match=match):
        load_catalog(tmp_path)
