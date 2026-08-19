"""Менеджер данных статистики сообщений и голосовой активности (Tortoise ORM).

Зеркалит паттерн :mod:`utils.activity_data_manager`, но работает с унифицированными
таблицами ``DailyUserStats`` / ``MonthlyUserStats``, где в одной строке лежат и
счётчик сообщений, и накопленные «умные» голосовые секунды.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from tortoise.exceptions import IntegrityError
from tortoise.expressions import F
from tortoise.functions import Sum
from tortoise.transactions import in_transaction

from .models import DailyUserStats, MonthlyUserStats
from .time_utils import moscow_today

logger = logging.getLogger("bot.utils.user_stats_data_manager")


@dataclass(frozen=True, slots=True)
class UserTotals:
    """Суммарные показатели одного пользователя за период.

    Attributes:
        user_id: ID пользователя Discord.
        messages: Количество сообщений.
        voice_seconds: Накопленные голосовые секунды.
    """

    user_id: int
    messages: int
    voice_seconds: int


class UserStatsDataManager:
    """CRUD и агрегаты для статистики сообщений и голоса."""

    def __init__(self) -> None:
        logger.info("Инициализация UserStatsDataManager (Tortoise ORM)")

    async def _increment_daily(
        self,
        user_id: int,
        *,
        messages: int,
        voice_seconds: int,
        target_date: date | None = None,
    ) -> None:
        """Атомарно прибавляет дельту к дневной строке, создавая её при отсутствии.

        Защищено от race condition тем же приёмом, что и
        :meth:`ActivityDataManager.update_activity`: сначала ``update`` через
        F-выражение, при отсутствии строки — ``create``, а на конкурентный
        ``IntegrityError`` повторяем ``update``.
        """
        if messages <= 0 and voice_seconds <= 0:
            return

        target_date_str = (target_date or moscow_today()).isoformat()
        try:
            updated = await DailyUserStats.filter(
                discord_user_id=user_id, date=target_date_str
            ).update(
                messages=F("messages") + messages,
                voice_seconds=F("voice_seconds") + voice_seconds,
            )
            if not updated:
                try:
                    await DailyUserStats.create(
                        discord_user_id=user_id,
                        date=target_date_str,
                        messages=messages,
                        voice_seconds=voice_seconds,
                    )
                except IntegrityError:
                    await DailyUserStats.filter(
                        discord_user_id=user_id, date=target_date_str
                    ).update(
                        messages=F("messages") + messages,
                        voice_seconds=F("voice_seconds") + voice_seconds,
                    )
        except Exception as e:
            logger.error(f"Ошибка инкремента daily_user_stats для {user_id}: {e}", exc_info=True)
            raise

    async def add_message(self, user_id: int) -> None:
        """Прибавляет одно сообщение пользователю за сегодня."""
        await self._increment_daily(user_id, messages=1, voice_seconds=0)

    async def add_voice_seconds(
        self,
        user_id: int,
        seconds: int,
        *,
        target_date: date | None = None,
    ) -> None:
        """Прибавляет голосовые секунды пользователю за указанную дату."""
        await self._increment_daily(
            user_id,
            messages=0,
            voice_seconds=seconds,
            target_date=target_date,
        )

    async def get_daily_totals(self, target_date: date) -> dict[int, UserTotals]:
        """Возвращает статистику всех пользователей за указанную дату."""
        target_str = target_date.isoformat()
        result: dict[int, UserTotals] = {}
        try:
            rows = await DailyUserStats.filter(date=target_str)
            for row in rows:
                if row.messages <= 0 and row.voice_seconds <= 0:
                    continue
                result[row.discord_user_id] = UserTotals(
                    user_id=row.discord_user_id,
                    messages=row.messages,
                    voice_seconds=row.voice_seconds,
                )
        except Exception as e:
            logger.error(f"Ошибка get_daily_totals за {target_str}: {e}", exc_info=True)
        return result

    async def get_pending_daily_dates(self, before_date: date) -> list[date]:
        """Возвращает дневные даты, которые ещё не перенесены в месячную таблицу."""
        try:
            raw_dates = (
                await DailyUserStats.filter(date__lt=before_date.isoformat())
                .distinct()
                .values_list("date", flat=True)
            )
        except Exception as e:
            logger.error("Ошибка получения дат user-stats для переноса: %s", e, exc_info=True)
            return []

        pending_dates: list[date] = []
        for raw_date in raw_dates:
            try:
                pending_dates.append(date.fromisoformat(str(raw_date)))
            except ValueError:
                logger.error("Некорректная дата в daily_user_stats: %r", raw_date)
        return sorted(set(pending_dates))

    async def get_daily_totals_by_prefix(self, prefix: str) -> dict[int, UserTotals]:
        """Агрегирует дневные строки, чья дата начинается с ``prefix`` (YYYY или YYYY-MM).

        Нужно, чтобы подмешать ещё не перенесённые в помесячную таблицу дни при
        построении wrapped за текущий/недавний период.
        """
        acc: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        try:
            rows = await DailyUserStats.filter(date__startswith=prefix)
            for row in rows:
                acc[row.discord_user_id][0] += row.messages
                acc[row.discord_user_id][1] += row.voice_seconds
        except Exception as e:
            logger.error(f"Ошибка get_daily_totals_by_prefix '{prefix}': {e}", exc_info=True)
        return {
            uid: UserTotals(user_id=uid, messages=m, voice_seconds=v)
            for uid, (m, v) in acc.items()
            if m > 0 or v > 0
        }

    @staticmethod
    def merge_totals(*dicts: dict[int, UserTotals]) -> dict[int, UserTotals]:
        """Складывает несколько словарей тоталов в один по user_id."""
        acc: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for d in dicts:
            for uid, totals in d.items():
                acc[uid][0] += totals.messages
                acc[uid][1] += totals.voice_seconds
        return {
            uid: UserTotals(user_id=uid, messages=m, voice_seconds=v) for uid, (m, v) in acc.items()
        }

    async def transfer_daily_to_monthly(self, target_date: date) -> bool:
        """Переносит дневные строки за дату в помесячную таблицу и удаляет дневные.

        Выполняется в одной транзакции. Возвращает True при успехе.
        """
        target_str = target_date.isoformat()
        year = target_date.year
        month = target_date.month
        try:
            async with in_transaction():
                daily_rows = await DailyUserStats.filter(date=target_str).all()
                if not daily_rows:
                    logger.info(f"Нет user-stats за {target_str} для переноса.")
                    return True

                existing = await MonthlyUserStats.filter(
                    year=year,
                    month=month,
                    discord_user_id__in=[r.discord_user_id for r in daily_rows],
                ).all()
                existing_ids = {m.discord_user_id for m in existing}

                to_create: list[MonthlyUserStats] = []
                for row in daily_rows:
                    if row.discord_user_id in existing_ids:
                        await MonthlyUserStats.filter(
                            discord_user_id=row.discord_user_id, year=year, month=month
                        ).update(
                            messages=F("messages") + row.messages,
                            voice_seconds=F("voice_seconds") + row.voice_seconds,
                        )
                    else:
                        to_create.append(
                            MonthlyUserStats(
                                discord_user_id=row.discord_user_id,
                                year=year,
                                month=month,
                                messages=row.messages,
                                voice_seconds=row.voice_seconds,
                            )
                        )
                        existing_ids.add(row.discord_user_id)

                if to_create:
                    await MonthlyUserStats.bulk_create(to_create)

                await DailyUserStats.filter(date=target_str).delete()
                logger.info(
                    f"User-stats за {target_str} перенесены в {year}-{month:02d} "
                    f"(обновлено {len(daily_rows) - len(to_create)}, создано {len(to_create)})."
                )
                return True
        except Exception as e:
            logger.error(f"Ошибка переноса user-stats за {target_str}: {e}", exc_info=True)
            return False

    async def get_monthly_totals(self, year: int, month: int) -> dict[int, UserTotals]:
        """Возвращает статистику всех пользователей за месяц из помесячной таблицы.

        Не подмешивает текущий день — для wrapped это вызывается по уже закрытым
        периодам. Текущий день при необходимости докидывается на стороне вызова.
        """
        result: dict[int, UserTotals] = {}
        try:
            rows = await MonthlyUserStats.filter(year=year, month=month)
            for row in rows:
                if row.messages <= 0 and row.voice_seconds <= 0:
                    continue
                result[row.discord_user_id] = UserTotals(
                    user_id=row.discord_user_id,
                    messages=row.messages,
                    voice_seconds=row.voice_seconds,
                )
        except Exception as e:
            logger.error(f"Ошибка get_monthly_totals за {year}-{month:02d}: {e}", exc_info=True)
        return result

    async def get_yearly_totals(self, year: int) -> dict[int, UserTotals]:
        """Возвращает суммарную статистику всех пользователей за год.

        Суммирует помесячные строки за год. Текущий незакрытый месяц/день в неё
        попадёт только после очередного переноса, поэтому свежий день при
        необходимости докидывается на стороне вызова.
        """
        acc: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        try:
            rows = (
                await MonthlyUserStats.filter(year=year)
                .group_by("discord_user_id")
                .annotate(total_messages=Sum("messages"), total_voice=Sum("voice_seconds"))
                .values("discord_user_id", "total_messages", "total_voice")
            )
            for row in rows:
                acc[row["discord_user_id"]][0] += row["total_messages"] or 0
                acc[row["discord_user_id"]][1] += row["total_voice"] or 0
        except Exception as e:
            logger.error(f"Ошибка get_yearly_totals за {year}: {e}", exc_info=True)

        return {
            uid: UserTotals(user_id=uid, messages=m, voice_seconds=v)
            for uid, (m, v) in acc.items()
            if m > 0 or v > 0
        }

    async def get_all_time_totals(self) -> dict[int, UserTotals]:
        """Возвращает статистику сообщений и голоса за всё время.

        Месячные и оставшиеся дневные строки не пересекаются: после успешного
        переноса дневные записи удаляются в той же транзакции.
        """
        acc: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        try:
            monthly_rows = (
                await MonthlyUserStats.all()
                .group_by("discord_user_id")
                .annotate(total_messages=Sum("messages"), total_voice=Sum("voice_seconds"))
                .values("discord_user_id", "total_messages", "total_voice")
            )
            for row in monthly_rows:
                acc[row["discord_user_id"]][0] += row["total_messages"] or 0
                acc[row["discord_user_id"]][1] += row["total_voice"] or 0

            daily_rows = (
                await DailyUserStats.all()
                .group_by("discord_user_id")
                .annotate(total_messages=Sum("messages"), total_voice=Sum("voice_seconds"))
                .values("discord_user_id", "total_messages", "total_voice")
            )
            for row in daily_rows:
                acc[row["discord_user_id"]][0] += row["total_messages"] or 0
                acc[row["discord_user_id"]][1] += row["total_voice"] or 0
        except Exception as e:
            logger.error(f"Ошибка get_all_time_totals: {e}", exc_info=True)

        return {
            uid: UserTotals(user_id=uid, messages=m, voice_seconds=v)
            for uid, (m, v) in acc.items()
            if m > 0 or v > 0
        }

    async def get_user_monthly(self, user_id: int, year: int, month: int) -> UserTotals:
        """Возвращает суммарную статистику одного пользователя за месяц.

        Берёт данные только из помесячной таблицы. Ещё не перенесённый текущий
        день/месяц при необходимости докидывается на стороне вызова через
        :meth:`get_daily_totals_by_prefix`.
        """
        messages = 0
        voice = 0
        try:
            rows = await MonthlyUserStats.filter(discord_user_id=user_id, year=year, month=month)
            for row in rows:
                messages += row.messages
                voice += row.voice_seconds
        except Exception as e:
            logger.error(
                f"Ошибка get_user_monthly для {user_id} за {year}-{month:02d}: {e}", exc_info=True
            )
        return UserTotals(user_id=user_id, messages=messages, voice_seconds=voice)

    async def get_user_yearly(self, user_id: int, year: int) -> UserTotals:
        """Возвращает суммарную статистику одного пользователя за год."""
        messages = 0
        voice = 0
        try:
            rows = await MonthlyUserStats.filter(discord_user_id=user_id, year=year)
            for row in rows:
                messages += row.messages
                voice += row.voice_seconds
        except Exception as e:
            logger.error(f"Ошибка get_user_yearly для {user_id} за {year}: {e}", exc_info=True)
        return UserTotals(user_id=user_id, messages=messages, voice_seconds=voice)

    @staticmethod
    def top_by_messages(totals: dict[int, UserTotals], limit: int) -> list[UserTotals]:
        """Сортирует пользователей по числу сообщений (по убыванию)."""
        ranked = [t for t in totals.values() if t.messages > 0]
        ranked.sort(key=lambda t: t.messages, reverse=True)
        return ranked[:limit]

    @staticmethod
    def top_by_voice(totals: dict[int, UserTotals], limit: int) -> list[UserTotals]:
        """Сортирует пользователей по голосовому времени (по убыванию)."""
        ranked = [t for t in totals.values() if t.voice_seconds > 0]
        ranked.sort(key=lambda t: t.voice_seconds, reverse=True)
        return ranked[:limit]
