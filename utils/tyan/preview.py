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
    """Генерирует 28 случайных выдач и 2 явно показательных события."""
    catalog = load_catalog()
    rng = random.Random(seed)
    history: list[Roll] = []
    lines = [
        "# /tyan — 30 примеров",
        "",
        "Получены тем же генератором, который использует команда.",
        "1–28: случайные сочетания из общего пула без гарантированно удачного режима.",
        "29–30: отдельно включённые микроивенты, а не их реальная частота.",
        "Возраст 18–40 / 41–55 / 56–80: 85/10/5%; рост 140–200; вес с привязкой к росту.",
        "",
    ]
    start = datetime(2026, 9, 10, 12, tzinfo=UTC)
    for index in range(28):
        config = TyanConfig(
            mother_chance=0,
            none_chance=0,
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
