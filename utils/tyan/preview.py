"""Воспроизводимые примеры для редакторской оценки, без Discord и базы."""

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from utils.tyan.catalog import load_catalog
from utils.tyan.config import TyanConfig
from utils.tyan.generator import generate_roll
from utils.tyan.types import Roll


def build_preview(*, seed: int = 20260910) -> str:
    """Генерирует 22 обычных, 6 положительных и 2 явно показательных события."""
    catalog = load_catalog()
    rng = random.Random(seed)
    history: list[Roll] = []
    lines = [
        "# /tyan — 30 примеров, редакция 4",
        "",
        "Получены тем же генератором, который будет использовать команда.",
        "Предыдущие подборки сохранены в tyan-preview-v1.md, v2.md и v3.md.",
        "1–22: обычная случайная выдача; 23–28: принудительно положительная.",
        "29–30: отдельно включённые микроивенты, а не их реальная частота.",
        "Возраст 18–80, рост 140–200 и вес 30–120 выбираются независимо.",
        "",
    ]
    start = datetime(2026, 9, 10, 12, tzinfo=UTC)
    for index in range(28):
        config = TyanConfig(
            mother_chance=0,
            none_chance=0,
            positive_chance=1 if index >= 22 else 0.20,
        )
        row = generate_roll(
            catalog,
            config,
            user_id=index % 15 + 1,
            now=start + timedelta(days=index // 15, seconds=index),
            history=history,
            rng=rng,
        )
        history.append(row)
        lines.append(f"{index + 1}. {row.text}")
    for index, kind in enumerate(("mother", "none"), start=29):
        config = TyanConfig(
            mother_chance=1 if kind == "mother" else 0,
            none_chance=1 if kind == "none" else 0,
        )
        row = generate_roll(
            catalog,
            config,
            user_id=1,
            now=start,
            history=[],
            member_ids=[2],
            rng=rng,
        )
        lines.append(f"{index}. {row.text.replace('<@2>', '@random-user')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    """Выводит примеры в консоль либо в указанный Markdown-файл."""
    parser = argparse.ArgumentParser(description="Предпросмотр /tyan без запуска бота")
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    preview = build_preview(seed=args.seed)
    if args.output:
        args.output.write_text(preview, encoding="utf-8")
    else:
        sys.stdout.write(preview)


if __name__ == "__main__":
    main()
