"""Согласованный снимок месячного wrapped без подмены ошибок пустыми данными."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from tortoise.transactions import in_transaction

from utils.models import DailyActivity, DailyUserStats, MonthlyActivity, MonthlyUserStats
from utils.user_stats_data_manager import UserStatsDataManager, UserTotals


@dataclass(frozen=True)
class MonthlySnapshot:
    """Статистика месяца вместе с ещё не перенесёнными дневными записями."""

    users: dict[int, UserTotals]
    games: dict[int, dict[str, int]]


class WrappedDataManager:
    """Читает данные отчёта в одной транзакции; ошибки передаёт вызывающему коду."""

    async def get_month(self, year: int, month: int) -> MonthlySnapshot:
        """Возвращает согласованный снимок месяца.

        Args:
            year: Год отчёта.
            month: Месяц от 1 до 12.

        Raises:
            ValueError: Некорректный период или отрицательный счётчик.
            Exception: Ошибка чтения БД, при которой отчёт нельзя публиковать.
        """
        date(year, month, 1)
        prefix = f"{year:04d}-{month:02d}-"
        async with in_transaction() as connection:
            monthly = await MonthlyUserStats.filter(year=year, month=month).using_db(connection)
            daily = await DailyUserStats.filter(date__startswith=prefix).using_db(connection)
            monthly_games = await MonthlyActivity.filter(year=year, month=month).using_db(
                connection
            )
            daily_games = await DailyActivity.filter(date__startswith=prefix).using_db(connection)

        # Перенос дневных записей тоже транзакционный: один и тот же день
        # не может попасть в обе половины этого снимка.
        user_parts: list[dict[int, UserTotals]] = []
        rows: list[MonthlyUserStats | DailyUserStats] = [*monthly, *daily]
        for row in rows:
            if row.messages < 0 or row.voice_seconds < 0:
                raise ValueError("Отрицательный счётчик активности")
            user_parts.append(
                {
                    row.discord_user_id: UserTotals(
                        row.discord_user_id, row.messages, row.voice_seconds
                    )
                }
            )
        games: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for game_row in monthly_games:
            if game_row.total_seconds_in_month < 0:
                raise ValueError("Отрицательное игровое время")
            if game_row.total_seconds_in_month:
                games[game_row.discord_user_id][game_row.game_name] += (
                    game_row.total_seconds_in_month
                )
        for daily_row in daily_games:
            if daily_row.seconds_played_today < 0:
                raise ValueError("Отрицательное игровое время")
            if daily_row.seconds_played_today:
                games[daily_row.discord_user_id][daily_row.game_name] += (
                    daily_row.seconds_played_today
                )
        return MonthlySnapshot(
            UserStatsDataManager.merge_totals(*user_parts),
            {uid: dict(values) for uid, values in games.items()},
        )
