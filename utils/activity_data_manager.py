"""Менеджер данных для отслеживания игровой активности пользователей с использованием Tortoise ORM."""

import logging
from collections import defaultdict
from datetime import date

from tortoise.exceptions import IntegrityError
from tortoise.expressions import F
from tortoise.functions import Sum

from .models import DailyActivity, MonthlyActivity

logger = logging.getLogger("bot.utils.activity_data_manager")


class ActivityDataManager:
    """Управляет данными об игровой активности пользователей с использованием Tortoise ORM."""

    def __init__(self, db_path: str | None = None) -> None:
        """Инициализирует менеджер данных активности.

        Args:
            db_path: Не используется в Tortoise ORM версии, оставлен для совместимости.
        """
        logger.info("Инициализация ActivityDataManager (Tortoise ORM)")

    async def update_activity(self, user_id: int, game_name: str, elapsed_seconds: int) -> None:
        """Обновляет дневную статистику активности в БД.

        Добавляет время к записи за текущий день или создает новую.
        Защищено от race condition: если параллельный вызов успевает создать
        запись между нашими update(→0) и create(), второй create() получит
        IntegrityError, и мы повторяем update — теперь строка уже существует
        и наша дельта прибавится атомарно.

        Args:
            user_id: ID пользователя Discord.
            game_name: Название игры.
            elapsed_seconds: Количество секунд, проведенных в игре.
        """
        if elapsed_seconds <= 0:
            return

        today_str = date.today().isoformat()  # Формат YYYY-MM-DD

        try:
            # Шаг 1: пытаемся обновить существующую запись атомарно через F-выражение.
            updated_count = await DailyActivity.filter(
                discord_user_id=user_id, game_name=game_name, date=today_str
            ).update(seconds_played_today=F("seconds_played_today") + elapsed_seconds)

            # Шаг 2: если строки не было — создаём, защищаясь от race condition.
            if not updated_count:
                try:
                    await DailyActivity.create(
                        discord_user_id=user_id,
                        game_name=game_name,
                        date=today_str,
                        seconds_played_today=elapsed_seconds,
                    )
                except IntegrityError:
                    # Конкурирующий вызов успел создать запись между нашими
                    # update→0 и create(). Повторяем update — теперь строка есть.
                    logger.debug(
                        "Race condition в update_activity для %s/%s/%s — повторяем update",
                        user_id,
                        game_name,
                        today_str,
                    )
                    await DailyActivity.filter(
                        discord_user_id=user_id, game_name=game_name, date=today_str
                    ).update(seconds_played_today=F("seconds_played_today") + elapsed_seconds)

            logger.debug(
                f"Обновлена дневная активность в БД для {user_id} - {game_name} "
                f"({today_str}): +{elapsed_seconds} сек."
            )
        except Exception as e:
            logger.error(f"Ошибка при обновлении daily_activity в БД: {e}", exc_info=True)

    async def get_daily_stats(self, target_date: date) -> dict[int, dict[str, int]]:
        """Получает всю статистику активности за указанную дату из БД.

        Args:
            target_date: Дата, за которую нужно получить статистику.

        Returns:
            Словарь вида {user_id: {game_name: seconds}}, содержащий статистику
            активности всех пользователей за указанную дату.
        """
        target_date_str = target_date.isoformat()
        daily_stats: dict[int, dict[str, int]] = defaultdict(dict)
        try:
            activities = await DailyActivity.filter(
                date=target_date_str, seconds_played_today__gt=0
            )

            for activity in activities:
                daily_stats[activity.discord_user_id][activity.game_name] = (
                    activity.seconds_played_today
                )

            logger.info(
                f"Загружена дневная статистика за {target_date_str} из БД: "
                f"{len(daily_stats)} пользователей."
            )
            return dict(daily_stats)
        except Exception as e:
            logger.error(
                f"Ошибка при получении daily_stats из БД за {target_date_str}: {e}", exc_info=True
            )
            return {}

    async def transfer_daily_to_monthly(self, target_date: date) -> bool:
        """Переносит агрегированные данные из daily_activity за указанную дату в monthly_activity.

        Также удаляет перенесенные дневные записи. Выполняется в одной транзакции.

        Args:
            target_date: Дата, за которую нужно перенести данные.

        Returns:
            True в случае успеха, False при ошибке.
        """
        target_date_str = target_date.isoformat()
        year = target_date.year
        month = target_date.month

        try:
            from tortoise.transactions import in_transaction

            async with in_transaction():
                # 1. Получаем данные для агрегации
                # Tortoise ORM пока не поддерживает сложные INSERT INTO ... SELECT ... GROUP BY
                # через ORM методы напрямую так же эффективно как raw SQL.
                # Но мы можем сделать это в два шага: SELECT + (UPDATE/INSERT)

                # Получаем сгруппированные данные за день
                # Нам нужно сгруппировать по user_id и game_name и просуммировать секунды
                # Но daily_activity уже уникальна по user_id, game_name, date.
                # Так как мы фильтруем по одной дате, группировка не нужна, просто берем все записи.

                daily_records = await DailyActivity.filter(
                    date=target_date_str, seconds_played_today__gt=0
                ).all()

                if not daily_records:
                    logger.info(f"Нет данных за {target_date_str} для переноса.")
                    return True

                # Преимущественно UPDATE → INSERT новых: на горячих юзерах большинство строк
                # уже есть, и оптом обновлять-вставлять заметно быстрее, чем по одному.
                existing = await MonthlyActivity.filter(
                    year=year,
                    month=month,
                    discord_user_id__in=[r.discord_user_id for r in daily_records],
                    game_name__in=[r.game_name for r in daily_records],
                ).all()
                existing_keys = {(m.discord_user_id, m.game_name) for m in existing}

                to_create: list[MonthlyActivity] = []
                for record in daily_records:
                    key = (record.discord_user_id, record.game_name)
                    if key in existing_keys:
                        await MonthlyActivity.filter(
                            discord_user_id=record.discord_user_id,
                            game_name=record.game_name,
                            year=year,
                            month=month,
                        ).update(
                            total_seconds_in_month=F("total_seconds_in_month")
                            + record.seconds_played_today
                        )
                    else:
                        to_create.append(
                            MonthlyActivity(
                                discord_user_id=record.discord_user_id,
                                game_name=record.game_name,
                                year=year,
                                month=month,
                                total_seconds_in_month=record.seconds_played_today,
                            )
                        )
                        # Чтобы не пытаться вставить дубль ещё раз в том же батче,
                        # если в daily вдруг есть две записи с тем же ключом.
                        existing_keys.add(key)

                if to_create:
                    await MonthlyActivity.bulk_create(to_create)

                logger.info(
                    f"Данные за {target_date_str} агрегированы и добавлены в "
                    f"monthly_activity за {year}-{month:02d} "
                    f"(обновлено: {len(daily_records) - len(to_create)}, "
                    f"создано: {len(to_create)})."
                )

                # 2. Удаляем обработанные записи из daily_activity
                await DailyActivity.filter(date=target_date_str).delete()
                logger.info(f"Удалены записи из daily_activity за {target_date_str}.")

                return True

        except Exception as e:
            logger.error(
                f"Ошибка при переносе данных за {target_date_str}: {e}",
                exc_info=True,
            )
            return False

    async def get_monthly_stats(self, user_id: int, year: int, month: int) -> dict[str, int]:
        """Получает статистику активности пользователя за указанный месяц и год из БД.

        Args:
            user_id: ID пользователя Discord.
            year: Год, за который нужно получить статистику.
            month: Месяц, за который нужно получить статистику.

        Returns:
            Словарь вида {game_name: seconds}, содержащий статистику
            активности пользователя за указанный месяц.
        """
        user_stats: dict[str, int] = {}
        try:
            activities = await MonthlyActivity.filter(
                discord_user_id=user_id, year=year, month=month, total_seconds_in_month__gt=0
            )

            for activity in activities:
                user_stats[activity.game_name] = activity.total_seconds_in_month

            logger.debug(
                f"Загружена месячная статистика для {user_id} за {year}-{month:02d}: "
                f"{len(user_stats)} игр."
            )
            return user_stats
        except Exception as e:
            logger.error(
                f"Ошибка при получении monthly_stats из БД для {user_id} ({year}-{month:02d}): {e}",
                exc_info=True,
            )
            return {}

    async def get_aggregated_monthly_stats(
        self, year: int, month: int
    ) -> dict[int, dict[str, int]]:
        """Получает всю статистику активности за указанный месяц и год из БД.

        Args:
            year: Год, за который нужно получить статистику.
            month: Месяц, за который нужно получить статистику.

        Returns:
            Словарь вида {user_id: {game_name: seconds}}, содержащий статистику
            активности всех пользователей за указанный месяц.
        """
        monthly_stats: dict[int, dict[str, int]] = defaultdict(dict)
        try:
            activities = await MonthlyActivity.filter(
                year=year, month=month, total_seconds_in_month__gt=0
            )

            for activity in activities:
                monthly_stats[activity.discord_user_id][activity.game_name] = (
                    activity.total_seconds_in_month
                )

            logger.info(
                f"Загружена агрегированная месячная статистика за {year}-{month:02d}: "
                f"{len(monthly_stats)} пользователей."
            )
            return dict(monthly_stats)
        except Exception as e:
            logger.error(
                f"Ошибка при получении агрегированной monthly_stats из БД "
                f"за {year}-{month:02d}: {e}",
                exc_info=True,
            )
            return {}

    async def get_all_time_stats(self, user_id: int) -> dict[str, int]:
        """Получает суммарную статистику активности пользователя за всё время из БД.

        Args:
            user_id: ID пользователя Discord.

        Returns:
            Словарь вида {game_name: seconds}, содержащий суммарную статистику
            активности пользователя за всё время.
        """
        user_stats: dict[str, int] = defaultdict(int)
        try:
            # 1. Суммируем данные из monthly_activity
            # Используем annotate для группировки и суммирования
            monthly_sums = (
                await MonthlyActivity.filter(discord_user_id=user_id, total_seconds_in_month__gt=0)
                .group_by("game_name")
                .annotate(total_seconds=Sum("total_seconds_in_month"))
                .values("game_name", "total_seconds")
            )

            for entry in monthly_sums:
                user_stats[entry["game_name"]] += entry["total_seconds"]

            # 2. Добавляем данные из daily_activity за СЕГОДНЯШНИЙ день
            today_str = date.today().isoformat()
            daily_activities = await DailyActivity.filter(
                discord_user_id=user_id, date=today_str, seconds_played_today__gt=0
            )

            for activity in daily_activities:
                user_stats[activity.game_name] += activity.seconds_played_today

            logger.debug(f"Загружена статистика за все время для {user_id}: {len(user_stats)} игр.")
            return dict(user_stats)
        except Exception as e:
            logger.error(
                f"Ошибка при получении all_time_stats из БД для {user_id}: {e}", exc_info=True
            )
            return {}
