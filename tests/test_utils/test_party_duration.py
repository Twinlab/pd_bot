"""Тесты для валидатора длительности /party."""

from datetime import UTC, datetime, timedelta

import pytest

from utils.party.duration import parse_minutes, parse_start_time


def test_start_time_is_moscow_and_remains_an_absolute_instant():
    now = datetime(2026, 10, 29, 17, tzinfo=UTC)
    start = parse_start_time("2026-10-30", "21:30", now=now)
    assert start == datetime(2026, 10, 30, 18, 30, tzinfo=UTC)


@pytest.mark.parametrize("day,clock", [
    ("2026-10-29", "19:00"), ("2026-10-29", "24:00"),
    ("2026-10-29", "через 30"), ("2026-11-10", "21:00"),
    ("2026-02-30", "21:00"),
])
def test_invalid_or_past_start_is_not_silently_shifted(day, clock):
    with pytest.raises(ValueError):
        parse_start_time(day, clock, now=datetime(2026, 10, 29, 17, tzinfo=UTC))


def test_new_year_and_timezone_boundary():
    assert parse_start_time("2027-01-01", "00:10", now=datetime(2026, 12, 31, 20, tzinfo=UTC)) == datetime(2026, 12, 31, 21, 10, tzinfo=UTC)


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
