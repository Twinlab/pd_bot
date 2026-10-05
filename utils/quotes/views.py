"""Личный предпросмотр и постоянные кнопки управления сохранёнными цитатами."""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING, Any, cast

import discord
from discord.ext import commands

from utils.error_handler import safe_send_error
from utils.quotes.service import report_quote_error
from utils.quotes.store import QuoteRecord

if TYPE_CHECKING:
    from cogs.fun import FunCog
    from utils.quotes.service import PendingQuote, QuoteService


class QuoteActionsView(discord.ui.View):
    """Открывает исходное сообщение и удаление из коллекции после рестарта."""

    def __init__(self, record: QuoteRecord) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Исходное сообщение", url=record.jump_url))
        self.add_item(DeleteQuoteButton(record.message_id))


class QuotePreviewView(discord.ui.View):
    """Хранит одну карточку до подтверждения владельцем или истечения срока."""

    def __init__(
        self, service: QuoteService, interaction: discord.Interaction, pending: PendingQuote
    ) -> None:
        super().__init__(timeout=service.config.preview_timeout)
        self.service = service
        self.original = interaction
        self.owner_id = interaction.user.id
        self.pending: PendingQuote | None = pending
        self.deadline = time.monotonic() + service.config.preview_timeout
        self._lock = asyncio.Lock()

    def release(self) -> None:
        """Освобождает байты рендера, даже если Discord уже удалил сообщение."""
        self.pending = None
        if self.service.previews.get(self.owner_id) is self:
            self.service.previews.pop(self.owner_id, None)
        self.stop()

    async def expire(self) -> None:
        """Закрывает устаревший предпросмотр и освобождает память."""
        async with self._lock:
            if self.pending is None:
                return
            self.release()
            try:
                await self.original.edit_original_response(
                    content="Предпросмотр закрыт. Чтобы добавить цитату, снова выбери «В цитаты».",
                    attachments=[],
                    view=None,
                )
            except discord.HTTPException:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Разрешает управление только владельцу действующего предпросмотра."""
        if interaction.user.id != self.owner_id:
            await safe_send_error(interaction, "Это предпросмотр другого участника.")
            return False
        if self.pending is None or self.service.closed or time.monotonic() >= self.deadline:
            await safe_send_error(interaction, "Предпросмотр истёк. Снова выбери «В цитаты».")
            await self.expire()
            return False
        return True

    @discord.ui.button(label="Сохранить цитату", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Сохраняет карточку один раз, повторно проверяя срок и владельца."""
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self._lock:
            if self.pending is None or time.monotonic() >= self.deadline:
                await safe_send_error(interaction, "Этот предпросмотр уже закрыт.")
                return
            pending = self.pending
            added = await self.service.commit(interaction, pending)
            self.release()
            await interaction.edit_original_response(
                content=(
                    "Цитата сохранена. Теперь она может выпасть через /quote."
                    if added
                    else "Цитата уже в коллекции — второй экземпляр не создан."
                ),
                attachments=[],
                view=QuoteActionsView(pending.record),
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Закрывает предпросмотр без сохранения файла."""
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self._lock:
            if self.pending is None:
                return
            self.release()
            await interaction.edit_original_response(
                content="Добавление отменено.", attachments=[], view=None
            )

    async def on_timeout(self) -> None:
        """Очищает кнопку и изображение после таймаута."""
        await self.expire()

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        """Показывает ошибку только владельцу предпросмотра."""
        await report_quote_error(interaction, error)


class DeleteQuoteButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"quote:delete:(?P<message_id>[1-9][0-9]{0,19})",
):
    """Восстанавливает удаление по ID без хранения каждого выданного сообщения."""

    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        super().__init__(
            discord.ui.Button(
                label="Удалить из коллекции",
                style=discord.ButtonStyle.secondary,
                custom_id=f"quote:delete:{message_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> DeleteQuoteButton:
        """Разбирает стабильный ID; авторизация выполняется после загрузки записи."""
        return cls(int(match["message_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        """Проверяет автора и открывает личное подтверждение удаления."""
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            cog = cast("FunCog | None", cast(commands.Bot, interaction.client).get_cog("FunCog"))
            if cog is None:
                raise ValueError("Цитаты сейчас перезагружаются. Попробуй чуть позже.")
            service = cog.quotes
            record = await service.removable(interaction, self.message_id)
            if record is None:
                await interaction.edit_original_response(
                    content="Эта цитата уже удалена из коллекции."
                )
                return
            await interaction.edit_original_response(
                content=(
                    "Удалить эту цитату из коллекции? Она больше не будет выпадать через /quote."
                ),
                view=QuoteDeleteConfirmView(service, interaction, self.message_id),
            )
        except Exception as error:
            # DynamicItem не вызывает View.on_error при ошибке callback.
            await report_quote_error(interaction, error)


class QuoteDeleteConfirmView(discord.ui.View):
    """Подтверждение удаления с повторной проверкой прав в момент действия."""

    def __init__(
        self, service: QuoteService, interaction: discord.Interaction, message_id: int
    ) -> None:
        super().__init__(timeout=60)
        self.service = service
        self.original = interaction
        self.owner_id = interaction.user.id
        self.message_id = message_id
        self.deadline = time.monotonic() + 60
        self._lock = asyncio.Lock()
        self._done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Не передаёт подтверждение другому пользователю и ограничивает его срок."""
        if interaction.user.id != self.owner_id:
            await safe_send_error(interaction, "Это подтверждение другого участника.")
            return False
        if self._done or time.monotonic() >= self.deadline:
            await safe_send_error(interaction, "Подтверждение истекло. Нажми удаление заново.")
            return False
        return True

    @discord.ui.button(label="Удалить цитату", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Удаляет только после повторной проверки владельца или модератора."""
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self._lock:
            if self._done or time.monotonic() >= self.deadline:
                return
            await self.service.delete(interaction, self.message_id)
            self._done = True
            self.stop()
            await interaction.edit_original_response(
                content="Цитата удалена из коллекции. Ранее отправленные копии в чатах сохраняются.",
                view=None,
            )

    @discord.ui.button(label="Оставить", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Закрывает подтверждение без удаления."""
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self._lock:
            if self._done:
                return
            self._done = True
            self.stop()
            await interaction.edit_original_response(content="Удаление отменено.", view=None)

    async def on_timeout(self) -> None:
        """Отключает устаревшее подтверждение."""
        async with self._lock:
            if self._done:
                return
            self._done = True
            self.stop()
            try:
                await self.original.edit_original_response(
                    content="Подтверждение истекло.", view=None
                )
            except discord.HTTPException:
                pass

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        """Отвечает на ошибки удаления приватно."""
        await report_quote_error(interaction, error)
