"""Журнал доставки Wrapped для единственного процесса бота."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Literal, Self

import discord
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from config.settings import WrappedScheduleConfig
from utils.time_utils import MOSCOW_TZ

logger = logging.getLogger("bot.wrapped.delivery")
STATE_PATH = Path("data/wrapped_delivery.json")
MAX_ATTEMPTS = 5
RETRY_DELAYS = (300, 900, 3600, 21600, 86400)
HISTORY_LIMIT = 1000
TERMINAL = frozenset({"sent", "permanent_forbidden", "manual_review", "skipped"})
Destination = discord.TextChannel | discord.DMChannel


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Повторяющийся ключ журнала Wrapped")
        result[key] = value
    return result


class DeliveryResult(StrEnum):
    """Результат доставки для существующих подтверждений и технических логов."""

    SENT = "sent"
    ALREADY_SENT = "already_sent"
    DEFERRED = "deferred"
    PERMANENT_FORBIDDEN = "permanent_forbidden"
    MANUAL_REVIEW = "manual_review"
    SKIPPED = "skipped"


class RecipientUnavailable(Exception):
    """Получатель больше не участвует в сервере; доставлять ему итог не нужно."""


class WrappedPeriod(BaseModel):
    """Тип и календарный период отчёта без привязки к месту публикации."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["monthly", "yearly", "personal"]
    year: int = Field(ge=1, le=9998)
    month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def validate_month(self) -> Self:
        """Запрещает неоднозначный ключ месяца или года."""
        if (self.kind == "monthly") != (self.month is not None):
            raise ValueError("Месяц требуется только для monthly")
        return self

    @property
    def key(self) -> str:
        """Возвращает стабильный ключ периода."""
        suffix = f"-{self.month:02d}" if self.month is not None else ""
        return f"{self.kind}:{self.year:04d}{suffix}"

    def delivery_key(self, recipient_id: int = 0) -> str:
        """Различает серверную доставку и отдельные личные сообщения."""
        return f"{self.key}:{recipient_id}"

    def filename(self, recipient_id: int = 0) -> str:
        """Маркирует вложение для восстановления неопределённой отправки."""
        return f"pd-wrapped-{self.delivery_key(recipient_id).replace(':', '-')}.png"


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    period: WrappedPeriod
    recipient_id: int = Field(ge=0)
    status: Literal[
        "ready", "retry", "pending", "sent", "permanent_forbidden", "manual_review", "skipped"
    ] = "ready"
    attempts: int = Field(default=0, ge=0, le=MAX_ATTEMPTS)
    destination_id: int | None = Field(default=None, gt=0)
    started_at: AwareDatetime | None = None
    next_retry: AwareDatetime | None = None
    message_id: int | None = Field(default=None, gt=0)
    last_error: str | None = None

    @model_validator(mode="after")
    def validate_delivery(self) -> Self:
        """Неполную запись нельзя трактовать как безопасную новую отправку."""
        if (self.period.kind == "personal") != (self.recipient_id > 0):
            raise ValueError("Неверный получатель Wrapped")
        if self.status == "sent" and self.message_id is None:
            raise ValueError("У отправленного Wrapped отсутствует message_id")
        if self.status == "pending" and (self.started_at is None or self.destination_id is None):
            raise ValueError("У незавершённой отправки отсутствует граница истории")
        return self


class _PersonalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recipients: list[int] | None = None
    attempts: int = Field(default=0, ge=0, le=MAX_ATTEMPTS)
    next_retry: AwareDatetime | None = None
    blocked: bool = False

    @model_validator(mode="after")
    def validate_recipients(self) -> Self:
        """Снимок получателей не должен содержать дублей или служебный ID."""
        if self.recipients is not None and (
            any(uid <= 0 for uid in self.recipients)
            or len(set(self.recipients)) != len(self.recipients)
        ):
            raise ValueError("Некорректный список получателей Wrapped")
        return self


class _Journal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    activated_at: AwareDatetime
    deliveries: dict[str, _Record] = Field(default_factory=dict)
    personal_batches: dict[str, _PersonalBatch] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_keys(self) -> Self:
        """Не позволяет повреждённому ключу обойти отметку уже отправленного отчёта."""
        for key, record in self.deliveries.items():
            if key != record.period.delivery_key(record.recipient_id):
                raise ValueError("Ключ доставки не соответствует записи")
        for key in self.personal_batches:
            if not key.isdigit() or not 1 <= int(key) <= 9998 or key != str(int(key)):
                raise ValueError("Некорректный ключ персональной рассылки")
        return self


class PreparedWrapped:
    """Подготовленная карточка; создание вложения отложено до попытки отправки."""

    def __init__(self, png: bytes, content: str, view: discord.ui.View | None = None) -> None:
        """Сохраняет существующее оформление сообщения без изменения рендера."""
        self.png = png
        self.content = content
        self.view = view


def scheduled_periods(
    schedule: WrappedScheduleConfig, activated_at: datetime, now: datetime
) -> list[WrappedPeriod]:
    """Возвращает слоты по МСК строго после активации и не позже текущего времени."""
    start = activated_at.astimezone(MOSCOW_TZ)
    end = now.astimezone(MOSCOW_TZ)
    result: list[tuple[datetime, WrappedPeriod]] = []
    for year in range(start.year, end.year + 1):
        for month in range(1, 13):
            slot = datetime(year, month, 1, schedule.hour, schedule.minute, tzinfo=MOSCOW_TZ)
            if start < slot <= end:
                previous = slot.date() - timedelta(days=1)
                result.append(
                    (slot, WrappedPeriod(kind="monthly", year=previous.year, month=previous.month))
                )
        for kind, month, day in (
            ("yearly", schedule.yearly_month, schedule.yearly_day),
            ("personal", schedule.personal_month, schedule.personal_day),
        ):
            if kind == "personal" and not schedule.personal_enabled:
                continue
            try:
                slot = datetime(year, month, day, schedule.hour, schedule.minute, tzinfo=MOSCOW_TZ)
            except ValueError:
                logger.error(
                    "Некорректная дата расписания Wrapped: %s %s-%s-%s", kind, year, month, day
                )
                continue
            if start < slot <= end:
                result.append((slot, WrappedPeriod(kind=kind, year=year)))
    return [period for _, period in sorted(result, key=lambda item: (item[0], item[1].key))]


class WrappedDelivery:
    """Сериализует ручные и автоматические отправки, сохраняя результат между перезапусками."""

    def __init__(
        self, state_path: Path = STATE_PATH, *, activated_at: datetime | None = None
    ) -> None:
        """Запоминает момент первого запуска; до первого обращения файлов не создаёт."""
        self.state_path = state_path
        self._activation = activated_at or datetime.now(UTC)
        self._lock = asyncio.Lock()
        self._seen_journal = False

    def _read(self) -> _Journal:
        try:
            raw = self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if self._seen_journal:
                raise RuntimeError("Журнал Wrapped исчез после загрузки") from None
            return _Journal(activated_at=self._activation)
        parsed = json.loads(raw, object_pairs_hook=_unique_json_object)
        if not isinstance(parsed, dict) or set(parsed) != set(_Journal.model_fields):
            raise ValueError("Неполный заголовок журнала Wrapped")
        for collection, model in (("deliveries", _Record), ("personal_batches", _PersonalBatch)):
            entries = parsed[collection]
            if not isinstance(entries, dict) or any(
                not isinstance(entry, dict) or set(entry) != set(model.model_fields)
                for entry in entries.values()
            ):
                raise ValueError("Неполная запись журнала Wrapped")
        journal = _Journal.model_validate_json(raw)
        self._seen_journal = True
        return journal

    def _write(self, journal: _Journal) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(journal.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.state_path)

    async def _save(self, journal: _Journal) -> None:
        writing = asyncio.create_task(asyncio.to_thread(self._write, journal))
        try:
            await asyncio.shield(writing)
        except asyncio.CancelledError:
            # Следующая операция под lock не должна обогнать ещё работающий os.replace.
            await writing
            raise
        self._seen_journal = True

    async def _load(self) -> _Journal:
        journal = await asyncio.to_thread(self._read)
        if not self._seen_journal:
            await self._save(journal)
        return journal

    @staticmethod
    def _ready(record: _Record | None, now: datetime) -> bool:
        return record is None or (
            record.status not in TERMINAL
            and (record.next_retry is None or record.next_retry <= now)
        )

    async def due_periods(
        self, schedule: WrappedScheduleConfig, *, now: datetime | None = None
    ) -> list[WrappedPeriod]:
        """Выбирает максимум один ожидающий период каждого типа за один проход."""
        async with self._lock:
            journal = await self._load()
            current = now or datetime.now(UTC)
            result: dict[str, WrappedPeriod] = {}
            candidates = {
                period.key: period
                for period in scheduled_periods(schedule, journal.activated_at, current)
            }
            # Ручная отправка старого периода уже разрешена: её повторы не являются backfill.
            for record in journal.deliveries.values():
                if record.period.kind != "personal" and self._ready(record, current):
                    candidates[record.period.key] = record.period
            periods = sorted(
                candidates.values(),
                key=lambda period: (period.year, period.month or 12, period.kind),
            )
            for period in periods:
                if period.kind in result:
                    continue
                if period.kind == "personal":
                    batch = journal.personal_batches.get(str(period.year))
                    if batch is not None:
                        if batch.blocked or (
                            batch.next_retry is not None and batch.next_retry > current
                        ):
                            continue
                        if batch.recipients is not None and not any(
                            self._ready(journal.deliveries.get(period.delivery_key(uid)), current)
                            for uid in batch.recipients
                        ):
                            continue
                elif not self._ready(journal.deliveries.get(period.delivery_key()), current):
                    continue
                result[period.kind] = period
            return list(result.values())

    async def personal_recipients(
        self,
        year: int,
        discover: Callable[[], Awaitable[list[int]]],
        *,
        now: datetime | None = None,
    ) -> list[int] | None:
        """Фиксирует состав рассылки один раз; ошибка чтения не превращается в пустую рассылку."""
        async with self._lock:
            journal = await self._load()
            current = now or datetime.now(UTC)
            batch = journal.personal_batches.setdefault(str(year), _PersonalBatch())
            if batch.recipients is not None:
                return list(batch.recipients)
            if batch.blocked or (batch.next_retry is not None and batch.next_retry > current):
                return None
            if batch.attempts >= MAX_ATTEMPTS:
                batch.blocked = True
                await self._save(journal)
                logger.error("Исчерпаны попытки определить получателей Wrapped %s", year)
                return None
            batch.attempts += 1
            batch.next_retry = current + timedelta(seconds=RETRY_DELAYS[batch.attempts - 1])
            await self._save(journal)
            try:
                async with asyncio.timeout(60):
                    recipients = sorted(set(await discover()))
                _PersonalBatch(recipients=recipients)
            except Exception:
                batch.blocked = batch.attempts >= MAX_ATTEMPTS
                await self._save(journal)
                logger.exception(
                    "Не удалось определить получателей Wrapped %s; attempt=%s", year, batch.attempts
                )
                return None
            batch.recipients = recipients
            batch.next_retry = None
            await self._save(journal)
            return list(recipients)

    @staticmethod
    def _check_history_access(destination: Destination) -> None:
        if isinstance(destination, discord.TextChannel):
            member = destination.guild.me
            if member is None:
                raise PermissionError("Бот отсутствует в кеше сервера")
            permissions = destination.permissions_for(member)
            if not permissions.view_channel or not permissions.read_message_history:
                raise PermissionError("Недостаточно прав для проверки истории Wrapped")

    async def _reconcile(
        self, destination: Destination, record: _Record, *, bot_id: int, now: datetime
    ) -> int | None:
        self._check_history_access(destination)
        if destination.id != record.destination_id or record.started_at is None:
            raise ValueError("Место незавершённой отправки Wrapped изменилось")
        if now < record.started_at:
            raise ValueError("Часы вернулись назад после попытки отправки Wrapped")
        seen = 0
        async with asyncio.timeout(30):
            async for message in destination.history(
                limit=HISTORY_LIMIT + 1,
                after=record.started_at - timedelta(minutes=1),
                before=now + timedelta(seconds=1),
                oldest_first=True,
            ):
                if message.author.id == bot_id and any(
                    attachment.filename == record.period.filename(record.recipient_id)
                    for attachment in message.attachments
                ):
                    return message.id
                seen += 1
                if seen > HISTORY_LIMIT:
                    raise RuntimeError("История Wrapped превышает безопасный предел проверки")
        self._check_history_access(destination)
        return None

    async def deliver(
        self,
        period: WrappedPeriod,
        *,
        recipient_id: int = 0,
        bot_id: int,
        destination: Callable[[], Awaitable[Destination]],
        prepare: Callable[[], Awaitable[PreparedWrapped]],
        now: datetime | None = None,
    ) -> DeliveryResult:
        """Отправляет карточку после записи pending либо восстанавливает прошлый результат."""
        async with self._lock:
            journal = await self._load()
            current = now or datetime.now(UTC)
            key = period.delivery_key(recipient_id)
            record = journal.deliveries.setdefault(
                key, _Record(period=period, recipient_id=recipient_id)
            )
            if record.status in TERMINAL:
                return (
                    DeliveryResult.ALREADY_SENT
                    if record.status == "sent"
                    else DeliveryResult(record.status)
                )
            if not self._ready(record, current):
                return DeliveryResult.DEFERRED
            if record.status == "pending":
                try:
                    async with asyncio.timeout(30):
                        channel = await destination()
                    found = await self._reconcile(
                        channel, record, bot_id=bot_id, now=now or datetime.now(UTC)
                    )
                except Exception:
                    record.status = "manual_review"
                    record.last_error = "history_unverified"
                    await self._save(journal)
                    logger.exception(
                        "Неопределённая отправка Wrapped %s: нужна ручная проверка истории", key
                    )
                    return DeliveryResult.MANUAL_REVIEW
                if found is not None:
                    record.status = "sent"
                    record.message_id = found
                    record.next_retry = None
                    await self._save(journal)
                    return DeliveryResult.ALREADY_SENT
            if record.attempts >= MAX_ATTEMPTS:
                record.status = "manual_review"
                record.last_error = "attempts_exhausted"
                await self._save(journal)
                logger.error("Исчерпаны попытки доставки Wrapped %s; нужна ручная проверка", key)
                return DeliveryResult.MANUAL_REVIEW

            record.attempts += 1
            record.status = "retry"
            record.next_retry = current + timedelta(seconds=RETRY_DELAYS[record.attempts - 1])
            await self._save(journal)
            try:
                async with asyncio.timeout(60):
                    channel = await destination()
                    self._check_history_access(channel)
                    prepared = await prepare()
            except (discord.Forbidden, RecipientUnavailable) as exc:
                record.status = (
                    "permanent_forbidden" if isinstance(exc, discord.Forbidden) else "skipped"
                )
                record.last_error = type(exc).__name__
                await self._save(journal)
                logger.info("Доставка Wrapped %s завершена без отправки: %s", key, record.status)
                return DeliveryResult(record.status)
            except Exception as exc:
                record.last_error = type(exc).__name__
                if record.attempts >= MAX_ATTEMPTS:
                    record.status = "manual_review"
                await self._save(journal)
                logger.exception(
                    "Не удалось подготовить Wrapped %s; attempt=%s", key, record.attempts
                )
                return (
                    DeliveryResult.MANUAL_REVIEW
                    if record.status == "manual_review"
                    else DeliveryResult.DEFERRED
                )

            record.destination_id = channel.id
            record.started_at = datetime.now(UTC) if now is None else current
            record.next_retry = record.started_at + timedelta(
                seconds=RETRY_DELAYS[record.attempts - 1]
            )
            record.status = "pending"
            await self._save(journal)
            try:
                async with asyncio.timeout(30):
                    message = await channel.send(
                        content=prepared.content,
                        file=discord.File(
                            BytesIO(prepared.png), filename=period.filename(recipient_id)
                        ),
                        view=prepared.view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except discord.Forbidden:
                record.status = "permanent_forbidden"
                record.last_error = "Forbidden"
                await self._save(journal)
                logger.info("Доставка Wrapped %s запрещена получателем или правами канала", key)
                return DeliveryResult.PERMANENT_FORBIDDEN
            except Exception as exc:
                record.last_error = type(exc).__name__
                await self._save(journal)
                logger.exception(
                    "Неопределённый результат отправки Wrapped %s; перед повтором проверим историю",
                    key,
                )
                return DeliveryResult.DEFERRED
            record.status = "sent"
            record.message_id = message.id
            record.next_retry = None
            record.last_error = None
            await self._save(journal)
            logger.info("Wrapped %s доставлен: message_id=%s", key, message.id)
            return DeliveryResult.SENT
