"""Объявления релизов с сохранением доставки между перезапусками."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import discord
import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from utils.ui import colors

BASE_DIR = Path(__file__).resolve().parent.parent
RELEASE_NOTES_PATH = BASE_DIR / "config" / "release_notes.yaml"
ANNOUNCEMENT_STATE_PATH = BASE_DIR / "data" / "release_announcements.json"


class ReleaseNote(BaseModel):
    """Авторский текст объявления; пустой текст не публикуется."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    title: str = Field(default="PD Bot обновился", min_length=1, max_length=150)
    text: str = Field(default="", max_length=3500)

    @property
    def marker(self) -> str:
        """Возвращает подпись версии для карточки и восстановления доставки."""
        return f"-# Обновление {self.id}"


class _Delivery(BaseModel):
    channel_id: int = Field(gt=0)
    started_at: AwareDatetime
    message_id: int | None = Field(default=None, gt=0)


class _AnnouncementState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    releases: dict[str, _Delivery] = Field(default_factory=dict)


def load_release_note(path: Path = RELEASE_NOTES_PATH) -> ReleaseNote:
    """Читает и проверяет описание релиза из поставляемого с ботом YAML."""
    return ReleaseNote.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def build_announcement_view(release: ReleaseNote) -> discord.ui.LayoutView:
    """Собирает статичную карточку с авторским текстом без изменения его разметки."""
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(
        discord.ui.Container(
            discord.ui.TextDisplay(f"## {release.title}\n{release.text}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(release.marker),
            accent_colour=colors.BRAND,
        )
    )
    return view


def _matches_release(message: discord.Message, release: ReleaseNote, bot_id: int) -> bool:
    return message.author.id == bot_id and any(
        isinstance(component, discord.Container)
        and any(
            isinstance(child, discord.TextDisplay) and child.content == release.marker
            for child in component.children
        )
        for component in message.components
    )


class ReleaseAnnouncer:
    """Отправляет каждый релиз один раз в рамках единственного процесса бота."""

    def __init__(self, state_path: Path = ANNOUNCEMENT_STATE_PATH) -> None:
        self.state_path = state_path
        self._lock = asyncio.Lock()

    def _read_state(self) -> _AnnouncementState:
        try:
            data = self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _AnnouncementState()
        # Повреждённый журнал нельзя считать пустым: это повторит старые объявления.
        return _AnnouncementState.model_validate_json(data)

    def _write_state(self, state: _AnnouncementState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as stream:
            stream.write(state.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, self.state_path)

    async def publish(
        self, release: ReleaseNote, channel: discord.TextChannel, *, bot_id: int
    ) -> bool:
        """Публикует релиз или восстанавливает результат прерванной отправки.

        Returns:
            Было ли отправлено новое сообщение в этом вызове.
        """
        if not release.text:
            return False
        async with self._lock:
            state = await asyncio.to_thread(self._read_state)
            delivery = state.releases.get(release.id)
            if delivery is not None and delivery.message_id is not None:
                return False

            if channel.guild.me is None:
                raise RuntimeError("Бот ещё не найден среди участников сервера.")
            permissions = channel.permissions_for(channel.guild.me)
            if not (
                permissions.view_channel
                and permissions.send_messages
                and permissions.read_message_history
            ):
                raise PermissionError(
                    "Для анонсов нужны просмотр канала, отправка и чтение истории."
                )

            if delivery is not None:
                if delivery.channel_id != channel.id:
                    raise ValueError(
                        "У незавершённого анонса другой канал; проверьте журнал доставки."
                    )
                # Discord мог принять сообщение до сбоя HTTP или записи журнала.
                async for message in channel.history(
                    limit=None,
                    after=delivery.started_at - timedelta(minutes=1),
                    oldest_first=True,
                ):
                    if _matches_release(message, release, bot_id):
                        delivery.message_id = message.id
                        await asyncio.to_thread(self._write_state, state)
                        return False
            else:
                delivery = _Delivery(channel_id=channel.id, started_at=datetime.now(UTC))
                state.releases[release.id] = delivery
                await asyncio.to_thread(self._write_state, state)

            message = await channel.send(
                view=build_announcement_view(release),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            delivery.message_id = message.id
            await asyncio.to_thread(self._write_state, state)
            return True
