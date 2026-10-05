"""Атомарное хранилище карточек цитат и их небольшого JSON-индекса."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("bot.quotes.store")
_MAX_INDEX_BYTES = 16 * 1024**2
_MAX_ID = 2**64 - 1
PositiveId = Annotated[int, Field(gt=0, le=_MAX_ID)]


class QuoteStoreError(Exception):
    """Ошибка хранилища с сообщением, пригодным для ответа пользователю."""


class QuoteLimitError(QuoteStoreError):
    """Карточка или хранилище превысили разрешённый объём."""


class QuoteRecord(BaseModel):
    """Метаданные карточки без текста сообщения и Discord-объектов."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )

    message_id: PositiveId
    guild_id: PositiveId
    channel_id: PositiveId
    author_id: PositiveId
    author_name: str = Field(min_length=1, max_length=100)
    author_display_name: str = Field(min_length=1, max_length=100)
    created_at: AwareDatetime
    saved_by: PositiveId
    saved_at: AwareDatetime
    size_bytes: int = Field(gt=0, le=2**31 - 1)

    @property
    def filename(self) -> str:
        """Возвращает стабильное имя, не зависящее от ника или пользовательского ввода."""
        return f"{self.message_id}.webp"

    @property
    def jump_url(self) -> str:
        """Возвращает ссылку на исходное сообщение в Discord."""
        return f"https://discord.com/channels/{self.guild_id}/{self.channel_id}/{self.message_id}"


class _Index(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    records: dict[str, QuoteRecord]

    @field_validator("version", mode="before")
    @classmethod
    def _integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Версия индекса должна быть целым числом")
        return value

    @model_validator(mode="after")
    def _matching_keys(self) -> Self:
        if any(key != str(record.message_id) for key, record in self.records.items()):
            raise ValueError("Ключ записи не совпадает с ID сообщения")
        return self


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Повторяющийся ключ в индексе цитат")
        result[key] = value
    return result


def _valid_id(message_id: int) -> None:
    if type(message_id) is not int or not 0 < message_id <= _MAX_ID:
        raise QuoteStoreError("Некорректный ID сообщения.")


class QuoteStore:
    """Последовательно сохраняет карточки; индекс перечитывается после каждого сбоя.

    Args:
        root: Выделенный каталог данных цитат; один экземпляр обслуживает все команды.
        max_total_bytes: Общий размер файлов каталога, включая индекс и остатки после сбоя.
        max_card_bytes: Максимальный размер одной готовой карточки.
        min_free_bytes: Минимальный остаток места после временной записи.
    """

    def __init__(
        self,
        root: Path,
        max_total_bytes: int = 256 * 1024**2,
        max_card_bytes: int = 256 * 1024,
        min_free_bytes: int = 2 * 1024**3,
    ) -> None:
        for value, minimum in ((max_total_bytes, 1), (max_card_bytes, 1), (min_free_bytes, 0)):
            if type(value) is not int or value < minimum:
                raise ValueError("Лимиты хранилища должны быть неотрицательными целыми числами")
        self.root = Path(root)
        self.index_path = self.root / "index.json"
        self.max_total_bytes = max_total_bytes
        self.max_card_bytes = max_card_bytes
        self.min_free_bytes = min_free_bytes
        self._lock = asyncio.Lock()
        self._seen_index = False

    async def _run[T](self, operation: Callable[[], T]) -> T:
        async with self._lock:
            task = asyncio.create_task(asyncio.to_thread(operation))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Нельзя отпустить lock, пока поток ещё меняет карточку или индекс.
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                with suppress(Exception):
                    task.result()
                raise
            except (OSError, ValueError) as exc:
                logger.warning("Операция хранилища цитат не выполнена: %s", type(exc).__name__)
                raise QuoteStoreError(
                    "Не удалось прочитать или сохранить цитату на диске."
                ) from exc

    def _load(self) -> _Index:
        if self.root.is_symlink() or self.index_path.is_symlink():
            raise QuoteStoreError("Хранилище цитат требует проверки администратором.")
        try:
            with self.index_path.open("rb") as stream:
                raw = stream.read(_MAX_INDEX_BYTES + 1)
        except FileNotFoundError:
            if self._seen_index or (self.root.exists() and any(self.root.iterdir())):
                raise QuoteStoreError(
                    "Индекс цитат отсутствует. Нужна проверка администратора."
                ) from None
            return _Index(version=1, records={})
        try:
            if len(raw) > _MAX_INDEX_BYTES:
                raise ValueError("Индекс цитат слишком большой")
            json.loads(raw, object_pairs_hook=_unique_keys)
            index = _Index.model_validate_json(raw)
        except ValueError as exc:
            raise QuoteStoreError("Индекс цитат повреждён. Нужна проверка администратора.") from exc
        self._seen_index = True
        return index

    @staticmethod
    def _index_bytes(index: _Index) -> bytes:
        encoded = index.model_dump_json(indent=2).encode("utf-8")
        if len(encoded) > _MAX_INDEX_BYTES:
            raise QuoteLimitError("В хранилище слишком много цитат.")
        return encoded

    def _sync_directory(self) -> None:
        if os.name == "posix":
            descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _atomic_write(self, path: Path, data: bytes) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        if path.is_symlink() or temporary.is_symlink():
            raise QuoteStoreError("Хранилище цитат требует проверки администратором.")
        try:
            with temporary.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._sync_directory()
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _total_bytes(self) -> int:
        if not self.root.exists():
            return 0
        total = 0

        def fail(error: OSError) -> None:
            raise error

        for folder, directories, files in os.walk(self.root, followlinks=False, onerror=fail):
            for name in directories + files:
                path = Path(folder, name)
                if path.is_symlink():
                    raise QuoteStoreError("Хранилище цитат требует проверки администратором.")
            total += sum(Path(folder, name).stat().st_size for name in files)
        return total

    def _check_free_space(self, write_bytes: int) -> None:
        parent = self.root
        while not parent.exists():
            parent = parent.parent
        if shutil.disk_usage(parent).free - write_bytes < self.min_free_bytes:
            raise QuoteLimitError(
                "На сервере мало свободного места. Новые цитаты пока не сохраняются."
            )

    async def list_records(self) -> list[QuoteRecord]:
        """Возвращает метаданные, начиная с последней сохранённой цитаты."""
        return await self._run(
            lambda: sorted(
                self._load().records.values(),
                key=lambda record: (record.saved_at, record.message_id),
                reverse=True,
            )
        )

    async def get(self, message_id: int) -> QuoteRecord | None:
        """Возвращает запись по исходному сообщению либо None."""
        _valid_id(message_id)
        return await self._run(lambda: self._load().records.get(str(message_id)))

    async def save(self, record: QuoteRecord, data: bytes) -> bool:
        """Сохраняет карточку и индекс; возвращает False для уже сохранённого сообщения."""
        return await self._run(lambda: self._save(record, data))

    def _save(self, record: QuoteRecord, data: bytes) -> bool:
        record = QuoteRecord.model_validate(record)
        if not isinstance(data, bytes) or len(data) != record.size_bytes:
            raise QuoteStoreError("Размер карточки не совпадает с её метаданными.")
        if len(data) > self.max_card_bytes:
            raise QuoteLimitError("Карточка слишком большая для сохранения.")
        index = self._load()
        key = str(record.message_id)
        if key in index.records:
            return False
        path = self.root / record.filename
        index.records[key] = record
        encoded = self._index_bytes(index)
        total = self._total_bytes()
        old_index_size = self.index_path.stat().st_size if self.index_path.exists() else 0
        old_card_size = path.stat().st_size if path.exists() else 0
        if total - old_index_size - old_card_size + len(data) + len(encoded) > self.max_total_bytes:
            raise QuoteLimitError("Хранилище цитат заполнено. Удалите ненужную цитату и повторите.")
        self._check_free_space(len(data) + len(encoded) + 8192)
        if not self.index_path.exists():
            # Даже первый crash после записи карточки должен оставить понятный пустой индекс.
            self._atomic_write(self.index_path, self._index_bytes(_Index(version=1, records={})))
            self._seen_index = True
        self._atomic_write(path, data)
        self._atomic_write(self.index_path, encoded)
        self._seen_index = True
        return True

    async def remove(self, message_id: int) -> bool:
        """Убирает запись до файла; повторный вызов может дочистить оставшийся файл."""
        _valid_id(message_id)
        return await self._run(lambda: self._remove(message_id))

    def _remove(self, message_id: int) -> bool:
        index = self._load()
        path = self.root / f"{message_id}.webp"
        if path.is_symlink():
            raise QuoteStoreError("Хранилище цитат требует проверки администратором.")
        existed = index.records.pop(str(message_id), None) is not None
        if existed:
            self._atomic_write(self.index_path, self._index_bytes(index))
        if path.exists():
            path.unlink()
            self._sync_directory()
            return True
        return existed

    async def read(self, message_id: int) -> bytes:
        """Читает зарегистрированную карточку с проверкой размера и лимитом байтов."""
        _valid_id(message_id)
        return await self._run(lambda: self._read(message_id))

    def _read(self, message_id: int) -> bytes:
        record = self._load().records.get(str(message_id))
        if record is None:
            raise QuoteStoreError("Цитата не найдена.")
        path = self.root / record.filename
        if path.is_symlink():
            raise QuoteStoreError("Хранилище цитат требует проверки администратором.")
        if record.size_bytes > self.max_card_bytes:
            raise QuoteLimitError("Карточка превышает допустимый размер.")
        with path.open("rb") as stream:
            data = stream.read(self.max_card_bytes + 1)
        if len(data) != record.size_bytes or len(data) > self.max_card_bytes:
            raise QuoteStoreError("Файл цитаты повреждён. Нужна проверка администратора.")
        return data
