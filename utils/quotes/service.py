"""Добавление текстовых цитат из общедоступных сообщений сервера."""

from __future__ import annotations

import asyncio
import io
import logging
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from config.settings import QuotesConfig
from utils.channel_permissions import public_message_channel_ids
from utils.error_handler import get_incident_error_message, new_incident_id, safe_send_error
from utils.quotes.render import QuoteCard, render_quote_card
from utils.quotes.store import QuoteRecord, QuoteStore, QuoteStoreError

if TYPE_CHECKING:
    from utils.quotes.views import QuotePreviewView

logger = logging.getLogger("bot.quotes")
_CUSTOM_EMOJI = re.compile(r"<a?:([A-Za-z0-9_]{1,32}):\d+>")


@dataclass(frozen=True)
class PendingQuote:
    """Карточка в памяти до подтверждения пользователем."""

    record: QuoteRecord
    image: bytes
    original_content: str
    display_content: str


async def report_quote_error(interaction: discord.Interaction, error: Exception) -> None:
    """Отвечает на ожидаемые ошибки и скрывает детали внутренних сбоев."""
    if isinstance(error, (ValueError, QuoteStoreError)):
        await safe_send_error(interaction, str(error))
        return
    incident = new_incident_id()
    logger.error(
        "Ошибка цитаты [%s]",
        incident,
        exc_info=(type(error), error, error.__traceback__),
    )
    await safe_send_error(interaction, get_incident_error_message(incident))


class QuoteService:
    """Связывает публичные сообщения, ограниченный рендер и постоянную коллекцию."""

    def __init__(
        self,
        config: QuotesConfig,
        guild_id: int | None,
        *,
        store: QuoteStore | None = None,
    ) -> None:
        self.config = config
        self.guild_id = guild_id
        self.store = store or QuoteStore(
            Path(config.generated_path),
            max_total_bytes=config.max_total_bytes,
            max_card_bytes=config.max_card_bytes,
            min_free_bytes=config.min_free_bytes,
        )
        self.closed = False
        self.previews: dict[int, QuotePreviewView] = {}
        self._render_slots = asyncio.Semaphore(2)
        self._preparing: set[int] = set()
        self._writes = asyncio.Lock()

    def public_channels(self, guild: discord.Guild | None) -> set[int]:
        """Проверяет актуальные права каналов перед каждой перепубликацией."""
        if guild is None or (self.guild_id is not None and guild.id != self.guild_id):
            return set()
        result = set()
        for channel_id in public_message_channel_ids(guild):
            channel = guild.get_channel_or_thread(channel_id)
            if isinstance(channel, (discord.TextChannel, discord.Thread)) and not channel.is_nsfw():
                result.add(channel_id)
        return result

    def validate_source(self, guild: discord.Guild | None, message: discord.Message) -> str:
        """Отсекает закрытые источники, подставных авторов и неподдерживаемый текст."""
        if self.closed:
            raise ValueError("Цитаты перезагружаются. Открой меню сообщения ещё раз чуть позже.")
        if guild is None or message.guild is None or guild.id != message.guild.id:
            raise ValueError("Цитаты доступны только для сообщений этого сервера.")
        if message.channel.id not in self.public_channels(guild):
            raise ValueError(
                "В цитаты можно добавлять только сообщения из общедоступных каналов без NSFW."
            )
        if message.author.bot or message.webhook_id is not None or message.is_system():
            raise ValueError("Выбери обычное текстовое сообщение участника, не бота или вебхука.")
        text = _CUSTOM_EMOJI.sub(r":\1:", message.clean_content).strip()
        if not text:
            raise ValueError(
                "В первой версии нужна текстовая цитата: картинки и вложения не сохраняются."
            )
        if len(text) > 1000 or len(message.content) > 4000:
            raise ValueError("Для читаемой карточки выбери сообщение не длиннее 1000 символов.")
        return text

    async def visible_records(self, guild: discord.Guild | None) -> list[QuoteRecord]:
        """Возвращает только записи из до сих пор открытых каналов этой гильдии."""
        allowed = self.public_channels(guild)
        if guild is None or not allowed:
            return []
        return [
            record
            for record in await self.store.list_records()
            if record.guild_id == guild.id and record.channel_id in allowed
        ]

    async def _avatar(self, author: discord.User | discord.Member) -> bytes | None:
        try:
            asset = author.display_avatar.with_static_format("png").with_size(256)
            data = await asyncio.wait_for(asset.read(), timeout=8)
            return data if len(data) <= 2 * 1024 * 1024 else None
        except (discord.HTTPException, TimeoutError, OSError):
            logger.warning("Аватар автора цитаты %s недоступен; использованы инициалы", author.id)
            return None

    async def prepare(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> PendingQuote:
        """Создаёт ограниченный предпросмотр в памяти без записи файлов."""
        text = self.validate_source(interaction.guild, message)
        if self._render_slots.locked():
            raise ValueError("Сейчас готовятся другие цитаты. Попробуй через несколько секунд.")
        async with self._render_slots:
            avatar = await self._avatar(message.author)
            card = QuoteCard(
                text=text,
                display_name=message.author.display_name,
                username=message.author.name,
                created_at=message.created_at,
                channel_name=getattr(message.channel, "name", "канал"),
            )
            task = asyncio.create_task(
                asyncio.to_thread(
                    render_quote_card, card, avatar, max_bytes=self.config.max_card_bytes
                )
            )
            try:
                data = await asyncio.shield(task)
            except asyncio.CancelledError:
                # Поток Pillow должен закончиться до освобождения слота рендера.
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
        if self.closed:
            raise ValueError("Бот перезагружает цитаты. Открой предпросмотр заново.")
        return PendingQuote(
            record=QuoteRecord(
                message_id=message.id,
                guild_id=interaction.guild.id,
                channel_id=message.channel.id,
                author_id=message.author.id,
                author_name=message.author.name,
                author_display_name=message.author.display_name,
                created_at=message.created_at,
                saved_by=interaction.user.id,
                saved_at=datetime.now(UTC),
                size_bytes=len(data),
            ),
            image=data,
            original_content=message.content,
            display_content=text,
        )

    async def start_preview(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        """Открывает личный предпросмотр или сообщает, что цитата уже сохранена."""
        from utils.quotes.views import QuoteActionsView, QuotePreviewView

        self.validate_source(interaction.guild, message)
        owner = interaction.user.id
        if owner in self._preparing:
            raise ValueError("Твоя карточка уже готовится. Дождись предпросмотра.")
        occupied = len(self.previews) + len(self._preparing) - int(owner in self.previews)
        if occupied >= self.config.max_pending_previews:
            raise ValueError("Открыто слишком много предпросмотров. Попробуй чуть позже.")
        self._preparing.add(owner)
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            existing = await self.store.get(message.id)
            if existing is not None:
                if existing.guild_id != interaction.guild_id:
                    raise ValueError("Цитата относится к другому серверу.")
                await interaction.edit_original_response(
                    content="Эта цитата уже в коллекции. Дубликат не создаётся.",
                    view=QuoteActionsView(existing),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            previous = self.previews.get(owner)
            if previous is not None:
                await previous.expire()
            pending = await self.prepare(interaction, message)
            view = QuotePreviewView(self, interaction, pending)
            self.previews[owner] = view
            try:
                await interaction.edit_original_response(
                    content=("Добавить в общую коллекцию автора? Сохранится текст без вложений."),
                    attachments=[discord.File(io.BytesIO(pending.image), filename="quote.webp")],
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (Exception, asyncio.CancelledError):
                view.release()
                raise
        finally:
            self._preparing.discard(owner)

    async def commit(self, interaction: discord.Interaction, pending: PendingQuote) -> bool:
        """Повторно проверяет источник и сохраняет именно подтверждённую карточку."""
        if interaction.user.id != pending.record.saved_by:
            raise ValueError("Этот предпросмотр принадлежит другому участнику.")
        guild = interaction.guild
        if guild is None or guild.id != pending.record.guild_id:
            raise ValueError("Цитату нельзя сохранить на другом сервере.")
        channel = guild.get_channel_or_thread(pending.record.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise ValueError("Исходный канал больше недоступен.")
        try:
            fresh = await channel.fetch_message(pending.record.message_id)
        except (discord.NotFound, discord.Forbidden) as error:
            raise ValueError("Исходное сообщение удалено или больше недоступно.") from error
        text = self.validate_source(guild, fresh)
        if (
            fresh.author.id != pending.record.author_id
            or fresh.content != pending.original_content
            or text != pending.display_content
        ):
            raise ValueError("Сообщение изменилось после предпросмотра. Открой «В цитаты» заново.")
        async with self._writes:
            if self.closed:
                raise ValueError("Цитаты перезагружаются. Открой предпросмотр заново.")
            return await self.store.save(pending.record, pending.image)

    async def send_record(self, ctx: commands.Context, record: QuoteRecord) -> None:
        """Публикует сохранённую карточку с оригиналом и кнопкой управления."""
        from utils.quotes.views import QuoteActionsView

        data = await self.store.read(record.message_id)
        if (
            ctx.guild is None
            or ctx.guild.id != record.guild_id
            or record.channel_id not in self.public_channels(ctx.guild)
        ):
            raise ValueError("Источник цитаты больше не общедоступен. Вызови /quote ещё раз.")
        await ctx.send(
            file=discord.File(io.BytesIO(data), filename=f"quote-{record.message_id}.webp"),
            view=QuoteActionsView(record),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def removable(
        self, interaction: discord.Interaction, message_id: int
    ) -> QuoteRecord | None:
        """Проверяет владельца по индексу, не доверяя содержимому custom_id."""
        if self.closed:
            raise ValueError("Цитаты перезагружаются. Попробуй ещё раз чуть позже.")
        record = await self.store.get(message_id)
        if self.closed:
            raise ValueError("Цитаты перезагружаются. Попробуй ещё раз чуть позже.")
        if record is None:
            return None
        if interaction.guild_id != record.guild_id:
            raise ValueError("Цитата относится к другому серверу.")
        if interaction.user.id != record.author_id and not interaction.permissions.manage_messages:
            raise ValueError("Удалить цитату из коллекции может её автор или модератор.")
        return record

    async def delete(self, interaction: discord.Interaction, message_id: int) -> bool:
        """Удаляет с повторной авторизацией и ожиданием записи при выгрузке кога."""
        async with self._writes:
            record = await self.removable(interaction, message_id)
            return await self.store.remove(message_id) if record is not None else False

    async def close(self) -> None:
        """Закрывает личные предпросмотры при перезагрузке кога."""
        self.closed = True
        # Новый ког не должен открыть второй индекс, пока старый ещё меняет файлы.
        async with self._writes:
            pass
        await asyncio.gather(*(view.expire() for view in list(self.previews.values())))
