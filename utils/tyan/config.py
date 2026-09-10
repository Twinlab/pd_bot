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
    age_weights: tuple[float, float, float] = (0.85, 0.10, 0.05)
    weight_weights: tuple[float, float, float] = (0.60, 0.30, 0.10)
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
        for name in ("part_weights", "age_weights", "weight_weights"):
            weights = getattr(self, name)
            if any(not 0 <= weight <= 1 for weight in weights):
                raise ValueError(f"{name}: веса должны лежать между 0 и 1")
            if sum(weights) <= 0:
                raise ValueError(f"{name}: хотя бы один вес должен быть положительным")
        if not any(
            low <= high and weight > 0
            for (low, high), weight in zip(self.age_ranges, self.age_weights, strict=True)
        ):
            raise ValueError("age_weights: нет доступного диапазона возраста")
        for height in range(self.height_min, self.height_max + 1):
            if not any(
                low <= high and weight > 0
                for (low, high), weight in zip(
                    self.weight_ranges(height), self.weight_weights, strict=True
                )
            ):
                raise ValueError(f"weight_weights: нет допустимого веса для роста {height}")
        return self

    @property
    def age_ranges(self) -> tuple[tuple[int, int], ...]:
        """Возвращает группы до 40, 41–55 и от 56 лет в пределах настроек."""
        return (
            (self.age_min, min(self.age_max, 40)),
            (max(self.age_min, 41), min(self.age_max, 55)),
            (max(self.age_min, 56), self.age_max),
        )

    def weight_ranges(self, height: int) -> tuple[tuple[int, int], ...]:
        """Возвращает три группы веса с нижней границей по росту."""
        # Это игровой баланс: снизу убираем 200/30, большой вес оставляем.
        lower = max(self.weight_min, (height - 79) // 2)
        return (
            (lower, min(self.weight_max, lower + 25)),
            (lower + 26, min(self.weight_max, lower + 50)),
            (lower + 51, self.weight_max),
        )

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
