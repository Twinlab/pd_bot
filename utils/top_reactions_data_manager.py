"""Менеджер данных для лидерборда сообщений с наибольшим числом реакций.

Этот модуль управляет двумя таблицами: ReactedMessage (метаданные сообщения) и
MessageReactor (записи о конкретных реакциях user × emoji). Поддерживает live-режим
(полные данные через события Discord) и исторический режим (импорт из дампа DCE,
где известен только суммарный счётчик реакций).

Лидерборд для периодов:
    - month: сообщения, опубликованные в текущем месяце.
    - year: сообщения, опубликованные в текущем году.
    - all: за всё время, объединяет live и исторические данные.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from tortoise.expressions import RawSQL

from .models import MessageReactor, ReactedMessage

logger = logging.getLogger("bot.utils.top_reactions_data_manager")

PeriodType = Literal["month", "year", "all"]


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """Одна позиция в лидерборде сообщений.

    Attributes:
        message_id: ID сообщения Discord.
        channel_id: ID канала, где сообщение опубликовано.
        author_id: ID автора сообщения.
        content: Текст сообщения (уже обрезанный).
        jump_url: Прямая ссылка на сообщение.
        posted_at: Дата публикации.
        reactor_count: Количество уникальных реакторов (или сумма реакций для исторических).
        is_historical: True, если данные взяты из исторического импорта (нет user_ids).
    """

    message_id: int
    channel_id: int
    author_id: int
    content: str
    jump_url: str
    posted_at: datetime
    reactor_count: int
    is_historical: bool


class TopReactionsDataManager:
    """Управляет хранением и запросами для лидерборда реакций."""

    def __init__(self, content_preview_length: int = 200) -> None:
        """Инициализирует менеджер.

        Args:
            content_preview_length: До какой длины обрезать content при сохранении.
        """
        self.content_preview_length = content_preview_length
        logger.info("Инициализация TopReactionsDataManager")

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Обрезает текст по длине с многоточием на конце."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    async def upsert_message(
        self,
        *,
        message_id: int,
        channel_id: int,
        author_id: int,
        content: str,
        jump_url: str,
        posted_at: datetime,
    ) -> None:
        """Создаёт или обновляет запись о сообщении.

        Args:
            message_id: ID сообщения Discord.
            channel_id: ID канала.
            author_id: ID автора.
            content: Текст сообщения (будет обрезан до content_preview_length).
            jump_url: Прямая ссылка на сообщение.
            posted_at: Дата публикации.
        """
        try:
            await ReactedMessage.update_or_create(
                message_id=message_id,
                defaults={
                    "channel_id": channel_id,
                    "author_id": author_id,
                    "content": self._truncate(content, self.content_preview_length),
                    "jump_url": jump_url,
                    "posted_at": posted_at,
                    "is_deleted": False,
                },
            )
        except Exception as e:
            logger.error(f"Ошибка upsert_message {message_id}: {e}", exc_info=True)

    async def add_reactor(self, *, message_id: int, user_id: int, emoji: str) -> bool:
        """Добавляет запись о реакции (message_id, user_id, emoji).

        Идемпотентна — повторное добавление того же тройного ключа возвращает False.

        Args:
            message_id: ID сообщения.
            user_id: ID пользователя, поставившего реакцию.
            emoji: Строковое представление эмодзи.

        Returns:
            True если запись создана, False если уже существовала или произошла ошибка.
        """
        try:
            _, created = await MessageReactor.get_or_create(
                message_id=message_id, user_id=user_id, emoji=emoji
            )
            return created
        except Exception as e:
            logger.error(
                f"Ошибка add_reactor msg={message_id} user={user_id} emoji={emoji}: {e}",
                exc_info=True,
            )
            return False

    async def remove_reactor(self, *, message_id: int, user_id: int, emoji: str) -> bool:
        """Удаляет конкретную запись (message_id, user_id, emoji).

        Returns:
            True если запись удалена, False если не найдена.
        """
        try:
            deleted = await MessageReactor.filter(
                message_id=message_id, user_id=user_id, emoji=emoji
            ).delete()
            return deleted > 0
        except Exception as e:
            logger.error(
                f"Ошибка remove_reactor msg={message_id} user={user_id} emoji={emoji}: {e}",
                exc_info=True,
            )
            return False

    async def remove_all_reactors_for_message(self, message_id: int) -> int:
        """Удаляет все записи о реакциях для сообщения (на on_raw_reaction_clear)."""
        try:
            return await MessageReactor.filter(message_id=message_id).delete()
        except Exception as e:
            logger.error(f"Ошибка remove_all_reactors_for_message {message_id}: {e}", exc_info=True)
            return 0

    async def remove_emoji_for_message(self, message_id: int, emoji: str) -> int:
        """Удаляет все записи о конкретном эмодзи на сообщении (on_raw_reaction_clear_emoji)."""
        try:
            return await MessageReactor.filter(message_id=message_id, emoji=emoji).delete()
        except Exception as e:
            logger.error(
                f"Ошибка remove_emoji_for_message {message_id} emoji={emoji}: {e}", exc_info=True
            )
            return 0

    async def message_exists(self, message_id: int) -> bool:
        """Проверяет, есть ли запись о сообщении в БД."""
        return await ReactedMessage.filter(message_id=message_id).exists()

    async def mark_deleted(self, message_id: int) -> None:
        """Помечает сообщение как удалённое (jump_url не будет работать)."""
        try:
            await ReactedMessage.filter(message_id=message_id).update(is_deleted=True)
        except Exception as e:
            logger.error(f"Ошибка mark_deleted {message_id}: {e}", exc_info=True)

    async def import_historical_message(
        self,
        *,
        message_id: int,
        channel_id: int,
        author_id: int,
        content: str,
        jump_url: str,
        posted_at: datetime,
        reaction_count: int,
    ) -> bool:
        """Импортирует историческое сообщение из дампа DCE (идемпотентно).

        Не перезаписывает существующие live-записи: если сообщение уже есть в БД с
        корректными live-данными, импорт пропускается. Это позволяет безопасно
        перезапускать импорт.

        Returns:
            True если запись создана, False если уже существовала.
        """
        try:
            existing = await ReactedMessage.get_or_none(message_id=message_id)
            if existing is not None:
                # Сохраняем historical_reaction_count только если live-данных ещё нет
                if existing.historical_reaction_count is None:
                    has_live = await MessageReactor.filter(message_id=message_id).exists()
                    if not has_live:
                        existing.historical_reaction_count = reaction_count
                        await existing.save(update_fields=["historical_reaction_count"])
                return False

            await ReactedMessage.create(
                message_id=message_id,
                channel_id=channel_id,
                author_id=author_id,
                content=self._truncate(content, self.content_preview_length),
                jump_url=jump_url,
                posted_at=posted_at,
                historical_reaction_count=reaction_count,
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка import_historical_message {message_id}: {e}", exc_info=True)
            return False

    async def get_leaderboard(
        self,
        period: PeriodType,
        limit: int,
        excluded_message_ids: set[int] | None = None,
    ) -> list[LeaderboardEntry]:
        """Возвращает топ сообщений за указанный период.

        Логика подсчёта:
            - Live-счётчик: COUNT(DISTINCT user_id) из MessageReactor для message_id.
            - Если live-счётчик > 0 — используем его.
            - Иначе используем historical_reaction_count (для исторических сообщений).
            - Если оба пустые — сообщение не попадает в выдачу.

        Args:
            period: 'month', 'year' или 'all'.
            limit: Сколько позиций вернуть.
            excluded_message_ids: Сообщения с этими id будут исключены из выдачи
                (например, сообщение role-реакций). Может быть None или пустым.

        Returns:
            Список LeaderboardEntry, отсортированный по убыванию счётчика.
        """
        try:
            now = datetime.now(UTC)
            qs = ReactedMessage.filter(is_deleted=False)
            if excluded_message_ids:
                qs = qs.exclude(message_id__in=list(excluded_message_ids))
            # Используем явные диапазоны вместо __year/__month: на SQLite Tortoise
            # транслирует их в EXTRACT(YEAR FROM ...), которого в SQLite нет.
            # Заодно даёт шанс воспользоваться индексом по posted_at.
            if period == "month":
                month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
                if now.month == 12:
                    month_end = datetime(now.year + 1, 1, 1, tzinfo=UTC)
                else:
                    month_end = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
                qs = qs.filter(posted_at__gte=month_start, posted_at__lt=month_end)
            elif period == "year":
                year_start = datetime(now.year, 1, 1, tzinfo=UTC)
                year_end = datetime(now.year + 1, 1, 1, tzinfo=UTC)
                qs = qs.filter(posted_at__gte=year_start, posted_at__lt=year_end)
            # for "all" — без доп. фильтров

            # Подзапрос на COUNT(DISTINCT user_id) для каждого сообщения.
            live_count_sql = (
                "(SELECT COUNT(DISTINCT user_id) FROM message_reactors "
                "WHERE message_reactors.message_id = reacted_messages.message_id)"
            )
            # Эффективный счётчик для сортировки: live, иначе historical, иначе 0.
            # Дублируем подзапрос (вместо ссылки на alias `live_count`), потому что
            # SQLite/большинство SQL не позволяет ссылаться на alias из той же SELECT-секции.
            effective_count_sql = (
                f"CASE WHEN {live_count_sql} > 0 THEN {live_count_sql} "
                "ELSE COALESCE(historical_reaction_count, 0) END"
            )
            qs = qs.annotate(
                live_count=RawSQL(live_count_sql),
                effective_count=RawSQL(effective_count_sql),
            )

            # Берём с запасом — чтобы после фильтрации (live_count > 0 OR historical > 0)
            # точно осталось `limit` записей. Запас x3 достаточно для практики.
            fetch_limit = max(limit * 3, limit + 50)
            # order_by принимает только строковые имена полей/аннотаций; передавать
            # RawSQL напрямую нельзя — pypika бросит TypeError на ordering[0].
            rows = await qs.order_by("-effective_count").limit(fetch_limit)

            entries: list[LeaderboardEntry] = []
            for row in rows:
                live = getattr(row, "live_count", 0) or 0
                if live > 0:
                    count = live
                    is_hist = False
                elif row.historical_reaction_count:
                    count = row.historical_reaction_count
                    is_hist = True
                else:
                    continue

                entries.append(
                    LeaderboardEntry(
                        message_id=row.message_id,
                        channel_id=row.channel_id,
                        author_id=row.author_id,
                        content=row.content,
                        jump_url=row.jump_url,
                        posted_at=row.posted_at,
                        reactor_count=count,
                        is_historical=is_hist,
                    )
                )
                if len(entries) >= limit:
                    break

            return entries
        except Exception as e:
            logger.error(f"Ошибка get_leaderboard period={period}: {e}", exc_info=True)
            return []
