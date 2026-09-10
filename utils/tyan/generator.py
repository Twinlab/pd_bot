"""Генератор сочетаний с историей повторов и общими редкими событиями."""

import random
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from utils.time_utils import MOSCOW_TZ
from utils.tyan.catalog import Catalog, Word
from utils.tyan.config import TyanConfig
from utils.tyan.types import Roll

Column = Literal["adjective_id", "archetype_id", "trait_id"]


def _choose(
    pool: tuple[Word, ...],
    column: Column,
    *,
    family_pool: tuple[Word, ...],
    user_id: int,
    now: datetime,
    history: Sequence[Roll],
    cooldown: int,
    pair_cooldown: int,
    archetype_id: str | None,
    rng: random.Random,
) -> Word:
    # Редакторский запрет пары сохраняется даже при исчерпании истории слов.
    pool = tuple(word for word in pool if archetype_id not in word.avoid_archetypes)
    if not pool:
        raise ValueError(f"Нет совместимых элементов для {archetype_id}")
    day = now.astimezone(MOSCOW_TZ).date()
    personal = {
        getattr(row, column)
        for row in history
        if row.user_id == user_id and (day - row.day).days < cooldown
    }
    today = (
        {row.archetype_id for row in history if row.day == day}
        if column == "archetype_id"
        else set()
    )
    paired = {
        getattr(row, column)
        for row in history
        if archetype_id is not None
        and row.archetype_id == archetype_id
        and (day - row.day).days < pair_cooldown
    }
    # Если короткий редакторский словарь исчерпан, ослабляем ограничения по
    # одному; неизменность дневного результата и перерыв событий не ослабляются.
    candidates = [word for word in pool if word.id not in personal | today | paired]
    if not candidates:
        candidates = [word for word in pool if word.id not in personal | today]
    if not candidates:
        candidates = [word for word in pool if word.id not in today]
    if not candidates:
        candidates = list(pool)
    recent = [row for row in history if (day - row.day).days < 7]
    counts = Counter(getattr(row, column) for row in recent)
    by_id = {word.id: word for word in family_pool}
    families = Counter(
        by_id[word_id].family or word_id
        for row in recent
        if (word_id := getattr(row, column)) in by_id
    )
    weights = [
        word.weight / (1 + 3 * counts[word.id] + families[word.family or word.id])
        for word in candidates
    ]
    return rng.choices(candidates, weights=weights, k=1)[0]


def generate_roll(
    catalog: Catalog,
    config: TyanConfig,
    *,
    user_id: int,
    now: datetime,
    history: Sequence[Roll],
    member_ids: Sequence[int] = (),
    rng: random.Random | None = None,
) -> Roll:
    """Возвращает сегодняшнюю выдачу либо создаёт новый результат.

    Args:
        catalog: Проверенные словари.
        config: Диапазоны и вероятности.
        user_id: Получатель результата.
        now: Текущее время с часовым поясом.
        history: История всего единственного сервера.
        member_ids: ID реальных участников, без ботов; автор исключается здесь.
        rng: Изолированный генератор для воспроизводимых проверок.

    Returns:
        Обычная тянка или одно заменяющее её событие.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now должен содержать часовой пояс")
    now = now.astimezone(UTC)
    day = now.astimezone(MOSCOW_TZ).date()
    history = [row for row in history if row.created_at <= now]
    for row in history:
        if row.user_id == user_id and row.day == day:
            return row
    rng = rng or random.Random()
    last_event = max(
        (row.created_at for row in history if row.kind in ("mother", "none")),
        default=None,
    )
    event_ready = last_event is None or now - last_event >= timedelta(
        days=config.event_cooldown_days
    )
    if event_ready:
        chance = rng.random()
        targets = sorted(set(member_ids) - {user_id})
        if chance < config.mother_chance and targets:
            target = rng.choice(targets)
            return Roll(
                user_id=user_id,
                day=day,
                created_at=now,
                kind="mother",
                text=f"тебе досталась мать <@{target}>",
                target_user_id=target,
            )
        if config.mother_chance <= chance < config.mother_chance + config.none_chance:
            return Roll(
                user_id=user_id,
                day=day,
                created_at=now,
                kind="none",
                text="тянки не досталось. сегодня дрочишь",
            )
    positive = rng.random() < config.positive_chance
    parts = rng.choices((1, 2, 3), weights=config.part_weights, k=1)[0]
    adjective_on = parts == 3 or (parts == 2 and rng.random() < 0.5)
    trait_on = parts == 3 or (parts == 2 and not adjective_on)
    if positive:
        # Положительный образ не требует обязательного третьего хвоста.
        adjective_on = True
        trait_on = parts == 3
    archetypes = tuple(
        word for word in catalog.archetypes if not positive or word.tone != "negative"
    )
    if not adjective_on and not trait_on:
        standalone = tuple(word for word in archetypes if word.standalone)
        if standalone:
            archetypes = standalone
        else:
            adjective_on = True
    archetype = _choose(
        archetypes,
        "archetype_id",
        family_pool=catalog.archetypes,
        user_id=user_id,
        now=now,
        history=history,
        cooldown=config.archetype_cooldown_days,
        pair_cooldown=config.pair_cooldown_days,
        archetype_id=None,
        rng=rng,
    )
    adjective = None
    trait = None
    if adjective_on:
        adjective = _choose(
            tuple(word for word in catalog.adjectives if not positive or word.tone == "positive"),
            "adjective_id",
            family_pool=catalog.adjectives,
            user_id=user_id,
            now=now,
            history=history,
            cooldown=config.adjective_cooldown_days,
            pair_cooldown=config.pair_cooldown_days,
            archetype_id=archetype.id,
            rng=rng,
        )
    if trait_on:
        trait = _choose(
            tuple(word for word in catalog.traits if not positive or word.tone == "positive"),
            "trait_id",
            family_pool=catalog.traits,
            user_id=user_id,
            now=now,
            history=history,
            cooldown=config.trait_cooldown_days,
            pair_cooldown=config.pair_cooldown_days,
            archetype_id=archetype.id,
            rng=rng,
        )
    age = rng.randint(config.age_min, config.age_max)
    height = rng.randint(config.height_min, config.height_max)
    weight = rng.randint(config.weight_min, config.weight_max)
    words = [f"{age}-летняя", f"{height}/{weight}"]
    if adjective:
        words.append(adjective.text)
    words.append(archetype.text)
    description = " ".join(words)
    if trait:
        separator = ", " if trait.joiner == "comma" else " "
        description += separator + trait.text
    return Roll(
        user_id=user_id,
        day=day,
        created_at=now,
        kind="normal",
        text="грац, тебе досталась " + description,
        adjective_id=adjective.id if adjective else None,
        archetype_id=archetype.id,
        trait_id=trait.id if trait else None,
        age=age,
        height=height,
        weight=weight,
    )
