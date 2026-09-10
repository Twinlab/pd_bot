"""Загрузка авторских словарей с постоянными ID."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Word(BaseModel):
    """Один элемент словаря; family объединяет близкие по смыслу варианты."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    text: str = Field(min_length=1, max_length=100)
    tone: Literal["positive", "neutral", "negative"]
    family: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,79}$")
    weight: float = Field(default=1.0, gt=0, le=100)
    joiner: Literal["space", "comma"] = "space"
    avoid_archetypes: tuple[str, ...] = ()
    standalone: bool = True

    @model_validator(mode="after")
    def validate_text(self) -> Self:
        """Не допускает управляющий текст Discord и случайные переносы."""
        if self.text != self.text.strip() or any(c in self.text for c in "\n\r\t@<>`"):
            raise ValueError("Элемент должен быть коротким текстом без упоминаний и разметки")
        return self


@dataclass(frozen=True)
class Catalog:
    """Три независимых набора фрагментов."""

    adjectives: tuple[Word, ...]
    archetypes: tuple[Word, ...]
    traits: tuple[Word, ...]


def _read_words(path: Path) -> tuple[Word, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"Словарь {path.name} должен быть непустым списком")
    words = tuple(Word.model_validate(item) for item in raw)
    ids = [word.id for word in words]
    texts = [word.text.casefold().replace("ё", "е") for word in words]
    if len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
        raise ValueError(f"Дубли ID или текстов в {path.name}")
    return words


@lru_cache(maxsize=4)
def load_catalog(directory: Path | None = None) -> Catalog:
    """Загружает и проверяет словари один раз на каталог."""
    base = directory or Path(__file__).with_name("content")
    catalog = Catalog(
        adjectives=_read_words(base / "adjectives.yaml"),
        archetypes=_read_words(base / "archetypes.yaml"),
        traits=_read_words(base / "traits.yaml"),
    )
    all_ids = [
        word.id
        for pool in (catalog.adjectives, catalog.archetypes, catalog.traits)
        for word in pool
    ]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("ID должны быть уникальны между всеми словарями")
    archetype_ids = {word.id for word in catalog.archetypes}
    for word in (*catalog.adjectives, *catalog.traits):
        unknown = set(word.avoid_archetypes) - archetype_ids
        if unknown:
            raise ValueError(f"Неизвестные типажи для {word.id}: {sorted(unknown)}")
    for archetype in catalog.archetypes:
        for name, pool in (
            ("прилагательных", catalog.adjectives),
            ("особенностей", catalog.traits),
        ):
            compatible = [word for word in pool if archetype.id not in word.avoid_archetypes]
            if not compatible:
                raise ValueError(f"Нет совместимых {name} для {archetype.id}")
    return catalog
