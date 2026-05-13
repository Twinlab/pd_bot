"""Тесты для валидатора длительности /party."""

from datetime import timedelta

import pytest

from utils.party.duration import parse_minutes


class TestParseMinutesValid:
    """Корректные значения внутри диапазона."""

    def test_min_boundary(self) -> None:
        """Граница min — допустима."""
        assert parse_minutes(1, min_minutes=1, max_minutes=240) == timedelta(minutes=1)

    def test_max_boundary(self) -> None:
        """Граница max — допустима."""
        assert parse_minutes(240, min_minutes=1, max_minutes=240) == timedelta(minutes=240)

    def test_typical_value(self) -> None:
        """15 минут — типичный сбор."""
        assert parse_minutes(15, min_minutes=1, max_minutes=240) == timedelta(minutes=15)


class TestParseMinutesInvalid:
    """Значения за пределами диапазона."""

    def test_below_min(self) -> None:
        """Меньше min — даёт ValueError с упоминанием минимума."""
        with pytest.raises(ValueError, match="Минимум"):
            parse_minutes(0, min_minutes=1, max_minutes=240)

    def test_negative(self) -> None:
        """Отрицательное число — тоже ValueError."""
        with pytest.raises(ValueError, match="Минимум"):
            parse_minutes(-5, min_minutes=1, max_minutes=240)

    def test_above_max(self) -> None:
        """Больше max — ValueError с упоминанием максимума."""
        with pytest.raises(ValueError, match="Максимум"):
            parse_minutes(300, min_minutes=1, max_minutes=240)
