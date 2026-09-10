"""Проверка распределения /tyan без Discord и базы данных."""

import argparse
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

from utils.tyan.catalog import load_catalog
from utils.tyan.config import TyanConfig
from utils.tyan.generator import generate_roll


def build_simulation(*, count: int = 10000, seed: int = 20260911) -> str:
    """Проверяет возраст, вес и текст на независимых новых выдачах."""
    if count < 1:
        raise ValueError("Количество выдач должно быть положительным")
    settings_path = Path(__file__).resolve().parents[2] / "config" / "bot_settings.yaml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))["fun"]["tyan"]
    config = TyanConfig.model_validate({**settings, "mother_chance": 0, "none_chance": 0})
    catalog = load_catalog()
    lookup = {
        word.id: word
        for pool in (catalog.adjectives, catalog.archetypes, catalog.traits)
        for word in pool
    }
    rng = random.Random(seed)
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)
    ages: Counter[str] = Counter()
    weights: Counter[str] = Counter()
    without_negative = 0
    invalid = 0
    examples: list[str] = []
    for index in range(count):
        roll = generate_roll(catalog, config, user_id=index + 1, now=now, history=[], rng=rng)
        assert roll.age is not None and roll.height is not None and roll.weight is not None
        ages["18–40" if roll.age <= 40 else "41–55" if roll.age <= 55 else "56–80"] += 1
        lower = max(config.weight_min, (roll.height - 79) // 2)
        weights[
            "Обычная"
            if roll.weight <= lower + 25
            else "Тяжёлая"
            if roll.weight <= lower + 50
            else "Самая тяжёлая"
        ] += 1
        invalid += int(
            not (
                config.age_min <= roll.age <= config.age_max
                and config.height_min <= roll.height <= config.height_max
                and lower <= roll.weight <= config.weight_max
            )
        )
        without_negative += int(
            all(
                lookup[word_id].tone != "negative"
                for word_id in (roll.adjective_id, roll.archetype_id, roll.trait_id)
                if word_id is not None
            )
        )
        if len(examples) < 15:
            examples.append(roll.text)
    lines = [
        "# /tyan: проверка баланса",
        "",
        f"Выдач: {count}; seed: {seed}; настройки: config/bot_settings.yaml.",
        "Независимые новые выдачи без истории. Микроивенты отключены только в этой проверке.",
        "",
        "| Параметр | Группа | Количество | Доля |",
        "| --- | --- | ---: | ---: |",
    ]
    for name, counts in (("Возраст", ages), ("Вес", weights)):
        for group, value in counts.items():
            lines.append(f"| {name} | {group} | {value} | {value / count:.2%} |")
    lines.extend(
        [
            "",
            f"Нарушений границ возраста/роста/веса: {invalid}.",
            f"Описаний без отрицательных меток: {without_negative} ({without_negative / count:.2%}).",
            "Слова выбираются из общего пула, без гарантированно положительного режима.",
            "",
            "Первые 15 результатов без отбора:",
            "",
            *(f"{index}. {text}" for index, text in enumerate(examples, 1)),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    """Выводит воспроизводимую проверку баланса в консоль или Markdown-файл."""
    parser = argparse.ArgumentParser(description="Проверка баланса /tyan без запуска бота")
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_simulation(count=args.count, seed=args.seed)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
