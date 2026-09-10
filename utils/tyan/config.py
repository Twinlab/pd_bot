"""Проверяемые настройки ежедневной выдачи /tyan."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TyanConfig(BaseModel):
    """Диапазоны параметров, вероятности и сроки защиты от повторов."""

    model_config = ConfigDict(extra="forbid")

    age_min: int = Field(default=18, ge=18, le=120)
    age_max: int = Field(default=80, ge=18, le=120)
    height_min: int = Field(default=140, ge=50, le=250)
    height_max: int = Field(default=200, ge=50, le=250)
    weight_min: int = Field(default=30, ge=20, le=250)
    weight_max: int = Field(default=120, ge=20, le=250)
    positive_chance: float = Field(default=0.20, ge=0, le=1)
    mother_chance: float = Field(default=0.005, ge=0, le=1)
    none_chance: float = Field(default=0.005, ge=0, le=1)
    event_cooldown_days: int = Field(default=14, ge=1, le=365)
    adjective_cooldown_days: int = Field(default=30, ge=1, le=365)
    archetype_cooldown_days: int = Field(default=60, ge=1, le=365)
    trait_cooldown_days: int = Field(default=90, ge=1, le=365)
    pair_cooldown_days: int = Field(default=120, ge=1, le=365)
    part_weights: tuple[float, float, float] = (0.20, 0.50, 0.30)

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        """Отклоняет перевёрнутые диапазоны и невозможные вероятности."""
        for name in ("age", "height", "weight"):
            if getattr(self, f"{name}_min") > getattr(self, f"{name}_max"):
                raise ValueError(f"{name}_min должен быть не больше {name}_max")
        if self.mother_chance + self.none_chance > 1:
            raise ValueError("Сумма вероятностей микроивентов не должна превышать 1")
        if any(not 0 <= weight <= 1 for weight in self.part_weights):
            raise ValueError("Веса числа элементов должны лежать между 0 и 1")
        if sum(self.part_weights) <= 0:
            raise ValueError("Хотя бы один вес числа элементов должен быть положительным")
        return self

    @property
    def history_days(self) -> int:
        """Возвращает достаточную глубину выборки истории."""
        return (
            max(
                self.event_cooldown_days,
                self.adjective_cooldown_days,
                self.archetype_cooldown_days,
                self.trait_cooldown_days,
                self.pair_cooldown_days,
                7,
            )
            + 1
        )
