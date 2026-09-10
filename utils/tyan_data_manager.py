"""Дневные выдачи /tyan и общая история антиповторов в SQLite."""

import logging
import random
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast

from tortoise.transactions import in_transaction

from utils.models import TyanRoll
from utils.time_utils import MOSCOW_TZ
from utils.tyan.catalog import Catalog
from utils.tyan.config import TyanConfig
from utils.tyan.generator import generate_roll
from utils.tyan.types import Roll, RollKind

logger = logging.getLogger("bot.utils.tyan")


def _to_roll(row: TyanRoll) -> Roll:
    if row.kind not in ("normal", "mother", "none"):
        raise ValueError(f"Неизвестный вид выдачи /tyan: {row.kind}")
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return Roll(
        user_id=row.discord_user_id,
        day=row.date,
        created_at=created_at.astimezone(UTC),
        kind=cast(RollKind, row.kind),
        text=row.text,
        adjective_id=row.adjective_id,
        archetype_id=row.archetype_id,
        trait_id=row.trait_id,
        age=row.age,
        height=row.height,
        weight=row.weight,
        target_user_id=row.target_user_id,
    )


class TyanDataManager:
    """Сохраняет выдачу до ответа в Discord, чтобы повторный вызов не давал переброс."""

    async def get_daily_roll(
        self,
        catalog: Catalog,
        config: TyanConfig,
        *,
        user_id: int,
        member_ids: Sequence[int] = (),
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> Roll:
        """Возвращает сохранённую тянку или атомарно выбирает и сохраняет новую.

        Args:
            catalog: Проверенные словари.
            config: Вероятности и сроки антиповторов.
            user_id: Автор команды.
            member_ids: Участники сервера без ботов.
            now: Время с часовым поясом; по умолчанию текущее UTC.
            rng: Генератор случайных чисел для воспроизводимых проверок.

        Returns:
            Снимок результата за московский день.
        """
        # SQLite-транзакция Tortoise сериализует доступ к единственному соединению:
        # проверка общего перерыва событий и запись должны быть в одной транзакции.
        async with in_transaction() as connection:
            current = now if now is not None else datetime.now(UTC)
            if current.tzinfo is None or current.utcoffset() is None:
                raise ValueError("Для /tyan требуется время с часовым поясом")
            current = current.astimezone(UTC)
            day = current.astimezone(MOSCOW_TZ).date()
            saved = (
                await TyanRoll.filter(discord_user_id=user_id, date=day)
                .using_db(connection)
                .first()
            )
            if saved is not None:
                return _to_roll(saved)

            rows = (
                await TyanRoll.filter(
                    date__gte=day - timedelta(days=config.history_days),
                    date__lte=day,
                )
                .using_db(connection)
                .order_by("created_at", "id")
            )
            roll = generate_roll(
                catalog,
                config,
                user_id=user_id,
                now=current,
                history=[_to_roll(row) for row in rows],
                member_ids=member_ids,
                rng=rng,
            )
            await TyanRoll.create(
                using_db=connection,
                discord_user_id=roll.user_id,
                date=roll.day,
                kind=roll.kind,
                text=roll.text,
                adjective_id=roll.adjective_id,
                archetype_id=roll.archetype_id,
                trait_id=roll.trait_id,
                age=roll.age,
                height=roll.height,
                weight=roll.weight,
                target_user_id=roll.target_user_id,
                # Остальная БД проекта хранит время как naive UTC (use_tz=False).
                created_at=roll.created_at.astimezone(UTC).replace(tzinfo=None),
            )
        logger.info("Выдана /tyan: user_id=%s, date=%s, kind=%s", user_id, day, roll.kind)
        return roll
