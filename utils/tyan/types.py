"""Неизменяемый результат выдачи, независимый от Discord и ORM."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

RollKind = Literal["normal", "mother", "none"]


@dataclass(frozen=True, slots=True)
class Roll:
    """Снимок результата: сегодняшняя строка не меняется при обновлении словаря."""

    user_id: int
    day: date
    created_at: datetime
    kind: RollKind
    text: str
    adjective_id: str | None = None
    archetype_id: str | None = None
    trait_id: str | None = None
    age: int | None = None
    height: int | None = None
    weight: int | None = None
    target_user_id: int | None = None
