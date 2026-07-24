"""Тесты календарного разбиения временных интервалов."""

from datetime import UTC, date, datetime

import pytest

from utils.time_utils import split_interval_by_local_date


def test_split_interval_inside_one_moscow_day() -> None:
    """Интервал без полуночи остаётся одной частью."""
    started_at = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)
    ended_at = datetime(2026, 7, 24, 10, 5, tzinfo=UTC)

    assert split_interval_by_local_date(started_at, ended_at) == [(date(2026, 7, 24), 300)]


def test_split_interval_at_moscow_midnight() -> None:
    """Секунды до и после московской полуночи попадают в разные даты."""
    started_at = datetime(2026, 7, 23, 20, 59, 58, tzinfo=UTC)
    ended_at = datetime(2026, 7, 23, 21, 0, 3, tzinfo=UTC)

    assert split_interval_by_local_date(started_at, ended_at) == [
        (date(2026, 7, 23), 2),
        (date(2026, 7, 24), 3),
    ]


def test_split_interval_preserves_total_with_microseconds() -> None:
    """Округление около полуночи не меняет полную длительность."""
    started_at = datetime(2026, 7, 23, 20, 59, 59, 800_000, tzinfo=UTC)
    ended_at = datetime(2026, 7, 23, 21, 0, 1, 100_000, tzinfo=UTC)

    parts = split_interval_by_local_date(started_at, ended_at)

    assert parts == [(date(2026, 7, 24), 1)]
    assert sum(seconds for _, seconds in parts) == 1


def test_split_interval_rejects_naive_datetime() -> None:
    """Naive datetime не должен молча интерпретироваться в локальном поясе."""
    with pytest.raises(ValueError, match="часовой пояс"):
        split_interval_by_local_date(
            datetime(2026, 7, 24, 10, 0),
            datetime(2026, 7, 24, 10, 1),
        )
