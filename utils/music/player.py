"""Кастомный плеер на базе :class:`wavelink.Player`.

Wavelink хранит очередь, текущий трек, громкость, паузу и фильтры внутри
самого плеера. Нам нужно дополнительно вести:

* ``text_channel`` — куда отправлять/обновлять сообщение "Сейчас играет";
* ``now_playing_message`` — последнее отправленное such сообщение, чтобы при
  смене трека редактировать его, а не плодить новые;
* привязку "трек -> заказчик" — для проверки прав на ``/skip`` / ``/pause``.

Привязка хранится прямо в ``track.extras.requester_id`` (Lavalink 4 поддерживает
``userData`` поле и wavelink пробрасывает его как ``extras``), что избавляет
нас от отдельного словаря.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

import discord
import wavelink

from .config import logger

if TYPE_CHECKING:
    from discord.ext import commands
    from discord.types.voice import GuildVoiceState as GuildVoiceStatePayload
    from discord.types.voice import VoiceServerUpdate as VoiceServerUpdatePayload

_connect_task: asyncio.Task[None] | None = None


class MusicPlayer(wavelink.Player):
    """Расширение :class:`wavelink.Player` с привязкой к текстовому каналу."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Инициализирует плеер с пустыми вспомогательными полями."""
        super().__init__(*args, **kwargs)
        self.text_channel: discord.TextChannel | discord.Thread | None = None
        self.now_playing_message: discord.Message | None = None

    async def on_voice_state_update(self, data: GuildVoiceStatePayload, /) -> None:
        """Завершает voice handshake независимо от порядка Gateway-событий."""
        await super().on_voice_state_update(data)

        voice = self._voice_state["voice"]
        logger.info(
            "Получен VOICE_STATE_UPDATE (channel=%s, session=%s, server=%s).",
            bool(data["channel_id"]),
            bool(voice.get("session_id")),
            bool(voice.get("token") and voice.get("endpoint")),
        )
        handshake_ready = bool(
            data["channel_id"]
            and voice.get("session_id")
            and voice.get("token")
            and voice.get("endpoint")
        )
        if not handshake_ready or self._connection_event.is_set():
            return

        # Discord не гарантирует порядок VOICE_STATE_UPDATE и VOICE_SERVER_UPDATE.
        # Wavelink 3.5.2 повторяет dispatch только для server-события, поэтому при
        # обратном порядке исходный connect ждёт до ChannelTimeoutException.
        logger.info(
            "Discord Voice handshake собран после VOICE_STATE_UPDATE; "
            "повторно передаём credentials в Lavalink."
        )
        await self._dispatch_voice_update()

    async def on_voice_server_update(self, data: VoiceServerUpdatePayload, /) -> None:
        """Логирует безопасное состояние server-части voice handshake."""
        logger.info(
            "Получен VOICE_SERVER_UPDATE (endpoint=%s, token=%s, state=%s).",
            bool(data.get("endpoint")),
            bool(data.get("token")),
            bool(self._voice_state["voice"].get("session_id")),
        )
        await super().on_voice_server_update(data)

    @staticmethod
    def assign_requester(track: wavelink.Playable, user: discord.Member) -> None:
        """Запоминает в ``track.extras`` ID заказавшего трек пользователя.

        Это нужно для проверки прав в ``/skip``/``/pause``/``/remove`` —
        обычный пользователь может пропускать только свои треки.
        """
        existing: dict[str, object] = dict(vars(track.extras)) if track.extras is not None else {}
        existing["requester_id"] = user.id
        track.extras = existing

    @staticmethod
    def get_requester_id(track: wavelink.Playable | None) -> int | None:
        """Возвращает ID заказчика трека, либо ``None``.

        Поддерживает оба варианта хранения ``extras``:
        :class:`wavelink.ExtrasNamespace` (продакшен) и обычный ``dict``
        (в тестовых сценариях, когда мы присваиваем словарь напрямую без
        wavelink-конвертера в свойстве).
        """
        if track is None:
            return None
        extras = track.extras
        if extras is None:
            return None
        if isinstance(extras, dict):
            requester = extras.get("requester_id")
        else:
            requester = getattr(extras, "requester_id", None)
        if requester is None:
            return None
        try:
            return int(requester)
        except (TypeError, ValueError):
            return None

    def can_control(
        self,
        member: discord.Member,
        *,
        admin_only: bool = False,
    ) -> bool:
        """Может ли участник управлять текущим воспроизведением.

        Правило: администратор гильдии может всё. Если ``admin_only=False`` и
        участник — заказчик текущего трека, тоже может. Иначе нет.

        Args:
            member: Участник Discord.
            admin_only: Если ``True``, только админ имеет доступ.

        Returns:
            ``True`` если разрешено.
        """
        if member.guild_permissions.administrator:
            return True
        if admin_only:
            return False
        return self.get_requester_id(self.current) == member.id


async def setup_node(bot: commands.Bot) -> None:
    """Запускает фоновое подключение к Lavalink-ноде.

    ВАЖНО: `wavelink.Pool.connect` блокируется до момента успешного подключения
    (с бесконечными retry при недоступности ноды), поэтому делать его
    синхронно из ``cog_load`` нельзя — иначе при отсутствии Lavalink на VM
    бот зависнет на старте и Discord-таймаут уронит весь процесс.

    Поэтому регистрация ноды и сам `connect` уезжают в фоновую задачу:
    музыкальный ког грузится мгновенно, бот стартует, а wavelink сам подцепит
    Lavalink, когда тот станет доступен. Если ноды нет вовсе — музыкальные
    команды будут отвечать ошибкой, но остальная функциональность бота не
    пострадает.

    Параметры читаются из ``bot.settings.music.lavalink``. Метод
    идемпотентен — повторный вызов не плодит дубликаты, если нода с тем же
    ``identifier`` уже в пуле.
    """
    settings = getattr(bot, "settings", None)
    if settings is None:
        from config import get_settings

        settings = get_settings()

    cfg = settings.music.lavalink
    inactive_timeout = settings.music.voice.inactive_timeout

    scheme = "https" if cfg.secure else "http"
    uri = f"{scheme}://{cfg.host}:{cfg.port}"

    # Если нода уже зарегистрирована — выходим, второй раз не подключаемся.
    pool_nodes: dict[str, wavelink.Node] = wavelink.Pool.nodes  # type: ignore[assignment]
    if cfg.identifier in pool_nodes:
        logger.info("Lavalink-нода %s уже зарегистрирована, пропускаем connect.", cfg.identifier)
        return

    node = wavelink.Node(
        identifier=cfg.identifier,
        uri=uri,
        password=cfg.password,
        inactive_player_timeout=inactive_timeout,
        client=bot,
    )

    async def _connect_in_background() -> None:
        logger.info("Подключение к Lavalink-ноде %s (%s)...", cfg.identifier, uri)
        try:
            await wavelink.Pool.connect(nodes=[node], client=bot)
        except Exception as exc:  # pragma: no cover - сетевая инициализация
            logger.error(
                "Фоновое подключение к Lavalink упало: %s. "
                "Музыкальные команды не будут работать, пока нода не появится.",
                exc,
                exc_info=True,
            )

    global _connect_task
    if _connect_task is not None and not _connect_task.done():
        logger.info("Подключение к Lavalink уже выполняется.")
        return
    _connect_task = asyncio.create_task(
        _connect_in_background(),
        name="wavelink-pool-connect",
    )


async def close_nodes() -> None:
    """Закрывает все Lavalink-ноды (используется при выгрузке кога)."""
    global _connect_task
    if _connect_task is not None and not _connect_task.done():
        _connect_task.cancel()
        with suppress(asyncio.CancelledError):
            await _connect_task
    _connect_task = None

    try:
        await wavelink.Pool.close()
        logger.info("Lavalink-ноды закрыты.")
    except Exception as exc:  # pragma: no cover - защитная обвязка
        logger.warning("Ошибка при закрытии Lavalink-нод: %s", exc)
