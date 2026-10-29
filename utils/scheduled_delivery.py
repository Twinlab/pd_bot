"""Сохранённая отправка сообщений с проверкой неопределённого результата в Discord."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import discord
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger("bot.scheduled_delivery")
Payload = dict[str, Any]


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: int = Field(gt=0)
    prepared_at: AwareDatetime
    parts: list[Payload] = Field(min_length=1, max_length=100)
    sent_ids: list[int] = Field(default_factory=list)
    pending_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_progress(self) -> _Entry:
        if len(self.sent_ids) > len(self.parts) or any(value <= 0 for value in self.sent_ids):
            raise ValueError("Некорректный прогресс отправки")
        if len(self.sent_ids) == len(self.parts) and self.pending_at is not None:
            raise ValueError("Завершённая отправка не может ожидать подтверждения")
        return self


class _Journal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    activated_at: AwareDatetime
    entries: dict[str, _Entry] = Field(default_factory=dict)


class ScheduledDelivery:
    """Один журнал на подсистему; снимок данных записывается до обращения к Discord."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._journal: _Journal | None = None

    async def _load(self) -> _Journal:
        if self._journal is None:
            try:
                raw = await asyncio.to_thread(self.path.read_bytes)
            except FileNotFoundError:
                journal = _Journal(activated_at=datetime.now(UTC))
                await self._save(journal)
            else:
                if len(raw) > 16 * 1024**2:
                    raise ValueError("Журнал отправок превышает допустимый размер")
                journal = _Journal.model_validate_json(raw)
            self._journal = journal
        return self._journal

    def _write(self, journal: _Journal) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(journal.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    async def _save(self, journal: _Journal) -> None:
        write = asyncio.create_task(asyncio.to_thread(self._write, journal))
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            await write
            raise
        except Exception:
            # После неудачной записи память уже может опережать сохранённый прогресс.
            self._journal = None
            raise

    async def activation_time(self) -> datetime:
        """Возвращает начало работы расписания, чтобы не публиковать старый архив."""
        async with self._lock:
            return (await self._load()).activated_at

    async def pending_keys(self, prefix: str) -> list[str]:
        """Возвращает незавершённые периоды, в том числе после смены даты."""
        async with self._lock:
            journal = await self._load()
            return sorted(
                key
                for key, entry in journal.entries.items()
                if key.startswith(prefix) and len(entry.sent_ids) < len(entry.parts)
            )

    async def _reconcile(
        self,
        entry: _Entry,
        channel: discord.TextChannel,
        bot_id: int,
        matches: Callable[[Payload, discord.Message], bool],
    ) -> int | None:
        assert entry.pending_at is not None
        if datetime.now(UTC) - entry.pending_at < timedelta(minutes=2):
            return None
        messages = [
            message
            async for message in channel.history(
                limit=101, after=entry.pending_at - timedelta(seconds=5), oldest_first=False
            )
        ]
        part = entry.parts[len(entry.sent_ids)]
        for message in messages:
            if message.author.id == bot_id and matches(part, message):
                return message.id
        # Без полного окна истории нельзя считать, что запрос точно не дошёл.
        return 0 if len(messages) < 101 else None

    async def deliver(
        self,
        key: str,
        *,
        channel: discord.TextChannel,
        bot_id: int,
        prepare: Callable[[], Awaitable[list[Payload]]],
        send: Callable[[Payload], Awaitable[discord.Message]],
        matches: Callable[[Payload, discord.Message], bool],
    ) -> list[Payload] | None:
        """Доставляет сохранённые части по порядку, проверяя прерванную отправку.

        Args:
            key: Уникальный период публикации внутри подсистемы.
            channel: Исходный канал доставки.
            bot_id: ID бота для проверки автора найденного сообщения.
            prepare: Сборщик снимка; повторно для существующего периода не вызывается.
            send: Отправка одной части, возвращающая сообщение Discord.
            matches: Проверка исходной части по содержимому сообщения в истории.

        Returns:
            Исходные части при полной доставке; None при необходимости повторной проверки.
        """
        async with self._lock:
            journal = await self._load()
            entry = journal.entries.get(key)
            if entry is None:
                parts = await prepare()
                entry = _Entry(channel_id=channel.id, prepared_at=datetime.now(UTC), parts=parts)
                journal.entries[key] = entry
                await self._save(journal)
            if entry.channel_id != channel.id:
                raise ValueError("Канал сохранённой отправки изменился; нужна ручная проверка")
            if len(entry.sent_ids) == len(entry.parts):
                return entry.parts
            while len(entry.sent_ids) < len(entry.parts):
                if entry.pending_at is not None:
                    found = await self._reconcile(entry, channel, bot_id, matches)
                    if found is None:
                        logger.warning("Отправка %s ожидает подтверждения по истории Discord", key)
                        return None
                    entry.pending_at = None
                    if found:
                        entry.sent_ids.append(found)
                    await self._save(journal)
                    if found:
                        continue
                entry.pending_at = datetime.now(UTC)
                await self._save(journal)
                try:
                    message = await send(entry.parts[len(entry.sent_ids)])
                except discord.Forbidden:
                    entry.pending_at = None
                    await self._save(journal)
                    raise
                if not isinstance(message.id, int) or message.id <= 0:
                    raise ValueError("Discord не подтвердил ID отправленного сообщения")
                entry.sent_ids.append(message.id)
                entry.pending_at = None
                await self._save(journal)
            cutoff = datetime.now(UTC) - timedelta(days=90)
            journal.entries = {
                name: value
                for name, value in journal.entries.items()
                if name == key
                or value.prepared_at >= cutoff
                or len(value.sent_ids) < len(value.parts)
            }
            await self._save(journal)
            return entry.parts
