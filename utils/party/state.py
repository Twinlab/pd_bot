"""Атомарный снимок сборов: только идентификаторы и данные, без Discord-объектов."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .manager import Party, PartyPhase

STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "party_state.json"
PositiveId = Annotated[int, Field(gt=0)]


class PartyRecord(BaseModel):
    """Сохранённое состояние одного опубликованного сбора."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    guild_id: PositiveId
    channel_id: PositiveId
    public_message_id: PositiveId
    role_id: PositiveId
    initiator_id: PositiveId
    count: int = Field(ge=1)
    comment: str
    created_at: AwareDatetime
    deadline: AwareDatetime
    image_url: str | None
    finish_when_full: bool
    joined_order: list[PositiveId]
    declined_order: list[PositiveId]
    dm_message_ids: dict[PositiveId, tuple[PositiveId, PositiveId]]
    last_press: dict[PositiveId, AwareDatetime]
    phase: PartyPhase
    confirmed: list[PositiveId]
    confirm_deadlines: dict[PositiveId, AwareDatetime]
    not_confirmed: list[PositiveId]
    ready_check_started: bool
    finalized: bool
    final_notice_attempted: bool

    @model_validator(mode="after")
    def validate_roster(self) -> Self:
        """Не позволяет восстановить неоднозначный состав или дедлайн."""
        if self.deadline < self.created_at:
            raise ValueError("Дедлайн сбора раньше его создания")
        for roster in (self.joined_order, self.declined_order, self.confirmed):
            if len(roster) != len(set(roster)):
                raise ValueError("В составе сбора есть повторяющиеся участники")
        if set(self.joined_order) & set(self.declined_order):
            raise ValueError("Участник одновременно готов и отказался")
        ready = set(self.joined_order[: self.count])
        if not set(self.confirmed) <= ready or not set(self.confirm_deadlines) <= ready:
            raise ValueError("Подтверждение не соответствует основному составу")
        if set(self.confirmed) & set(self.confirm_deadlines):
            raise ValueError("Подтвердивший участник одновременно ожидает подтверждения")
        return self

    @classmethod
    def from_party(cls, party: Party) -> PartyRecord:
        """Копирует сериализуемые поля под блокировкой владельца состояния."""
        return cls.model_validate({name: getattr(party, name) for name in cls.model_fields})

    def to_party(self) -> Party:
        """Восстанавливает доменное состояние без сетевых запросов."""
        return Party(**self.model_dump())


class PartySnapshot(BaseModel):
    """Версионированный снимок активных и ещё не очищенных закрытых сборов."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    parties: list[PartyRecord]
    cooldowns: dict[PositiveId, AwareDatetime]

    @field_validator("version", mode="before")
    @classmethod
    def validate_version(cls, value: object) -> object:
        """Булево значение или float не являются версией формата."""
        if type(value) is not int:
            raise ValueError("Версия снимка должна быть целым числом")
        return value

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        """Запрещает две версии одного сбора в одном снимке."""
        if len({party.id for party in self.parties}) != len(self.parties):
            raise ValueError("В снимке повторяется идентификатор сбора")
        return self


class PartyStateStore:
    """Читает строгий снимок и заменяет файл только после полной записи."""

    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path

    def load(self) -> PartySnapshot:
        """Возвращает пустое состояние только при отсутствии файла."""
        try:
            content = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return PartySnapshot(version=1, parties=[], cooldowns={})
        json.loads(content, object_pairs_hook=_unique_keys)
        return PartySnapshot.model_validate_json(content)

    def _write(self, snapshot: PartySnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(snapshot.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    async def save(self, snapshot: PartySnapshot) -> None:
        """Дожидается атомарной записи даже при отмене вызывающей задачи."""
        write = asyncio.create_task(asyncio.to_thread(self._write, snapshot))
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            await write
            raise


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"В снимке повторяется ключ {key}")
        result[key] = value
    return result
