"""Личная история сохранённых выдач с переходами по датам."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Any

import discord
from discord.ext import commands

from utils.error_handler import safe_send, safe_send_error
from utils.tyan.types import Roll
from utils.tyan_data_manager import TyanDataManager

logger = logging.getLogger("bot.utils.tyan")


class _HistoryRow(discord.ui.ActionRow["TyanHistoryView"]):
    @discord.ui.button(label="Новее", emoji="◀️")
    async def newer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.view is not None:
            await self.view.change_page(interaction, older=False)

    @discord.ui.button(label="Старее", emoji="▶️")
    async def older(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.view is not None:
            await self.view.change_page(interaction, older=True)


class TyanHistoryView(discord.ui.LayoutView):
    """Показывает одну исходную карточку; курсоры не сдвигаются из-за новых выдач."""

    def __init__(self, manager: TyanDataManager, user_id: int, rolls: list[Roll]) -> None:
        super().__init__(timeout=300)
        self.manager = manager
        self.user_id = user_id
        self.rolls = rolls
        self.cursors: list[date | None] = [None]
        self.message: discord.Message | None = None
        self._lock = asyncio.Lock()
        self._render()

    def _render(self) -> None:
        self.clear_items()
        if not self.rolls:
            self.add_item(
                discord.ui.TextDisplay("История пока пустая. Получи первую тянку через /tyan.")
            )
            return
        roll = self.rolls[0]
        color = {"mother": 0xF0B232, "none": 0x747F8D}.get(roll.kind, 0x5865F2)
        container: discord.ui.Container = discord.ui.Container(accent_colour=color)
        container.add_item(discord.ui.TextDisplay(f"## Моя тянка · {roll.day:%d.%m.%Y}"))
        container.add_item(discord.ui.TextDisplay(roll.text))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("-# Сохранённая выдача. Даты — по Москве."))
        row = _HistoryRow()
        row.newer.disabled = len(self.cursors) == 1
        row.older.disabled = len(self.rolls) < 2
        container.add_item(row)
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ограничивает просмотр владельцем и временем жизни меню."""
        if interaction.user.id != self.user_id:
            await safe_send_error(interaction, "Открой свою историю через /tyan_history.")
            return False
        if self.is_finished():
            await safe_send_error(interaction, "Меню устарело. Открой /tyan_history заново.")
            return False
        return True

    async def change_page(self, interaction: discord.Interaction, *, older: bool) -> None:
        """Читает соседнюю выдачу, не изменяя текущий результат /tyan."""
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self._lock:
            if self.is_finished() or not self.rolls:
                return
            cursors = list(self.cursors)
            if older:
                if len(self.rolls) < 2:
                    return
                cursors.append(self.rolls[0].day)
            elif len(cursors) > 1:
                cursors.pop()
            else:
                return
            rolls = await self.manager.get_history(self.user_id, before=cursors[-1])
            if not rolls:
                await safe_send_error(interaction, "Эта часть истории больше недоступна.")
                return
            self.cursors, self.rolls = cursors, rolls
            self._render()
            await interaction.edit_original_response(
                view=self, allowed_mentions=discord.AllowedMentions.none()
            )

    async def on_timeout(self) -> None:
        """Убирает активные кнопки у истёкшего меню."""
        async with self._lock:
            for item in self.walk_children():
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        """Сообщает о недоступной истории, сохраняя причину в журнале."""
        logger.error("Ошибка просмотра истории /tyan", exc_info=error)
        await safe_send_error(interaction, "Не удалось загрузить историю. Попробуй позже.")


async def send_tyan_history(ctx: commands.Context | discord.Interaction) -> None:
    """Открывает историю автора команды или нажавшего кнопку участника."""
    user_id = ctx.user.id if isinstance(ctx, discord.Interaction) else ctx.author.id
    if isinstance(ctx, discord.Interaction):
        await ctx.response.defer(ephemeral=True, thinking=True)
    elif ctx.interaction is not None:
        await ctx.defer(ephemeral=True)
    manager = TyanDataManager()
    rolls = await manager.get_history(user_id)
    view = TyanHistoryView(manager, user_id, rolls)
    view.message = await safe_send(
        ctx, view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )


class TyanHistoryButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tyan:history"):
    """Кнопка открывает собственную историю и работает после перезапуска бота."""

    def __init__(self) -> None:
        super().__init__(
            discord.ui.Button(label="Моя история", custom_id="tyan:history", emoji="📜")
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: re.Match[str]
    ) -> TyanHistoryButton:
        """Восстанавливает обработчик без хранения отдельной View для каждой выдачи."""
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        """Показывает личное меню без упоминаний в общем канале."""
        if interaction.guild is None:
            await safe_send_error(interaction, "История доступна только на сервере.")
            return
        try:
            await send_tyan_history(interaction)
        except Exception as error:
            logger.error("Ошибка открытия истории /tyan", exc_info=error)
            await safe_send_error(interaction, "Не удалось загрузить историю. Попробуй позже.")
