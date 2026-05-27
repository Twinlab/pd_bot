"""View с кнопками «Готов» / «Не готов» для DM-сообщения сбора пати.

Каждое DM-сообщение получает свой экземпляр view: timeout привязан к
``deadline`` пати. После таймаута Discord сам деактивирует кнопки клиентам;
явное обновление embed-а делает cog при финализации.

Кулдаун между нажатиями (любых кнопок) — на одного пользователя в рамках
одного пати. Значение берётся из ``settings.party.button_cooldown_seconds``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord

from config import get_settings

if TYPE_CHECKING:
    from cogs.party import PartyCog
    from utils.party.manager import Party

logger = logging.getLogger("bot.utils.party_views")


class PartyView(discord.ui.View):
    """Две кнопки в DM: «Готов» / «Не готов» для конкретного сбора."""

    def __init__(self, *, cog: PartyCog, party: Party) -> None:
        # Timeout = сколько осталось до закрытия. Discord после него отключит
        # кнопки на клиенте — больше нажать нельзя.
        remaining = (party.deadline - datetime.now(UTC)).total_seconds()
        super().__init__(timeout=max(1.0, remaining))
        self.cog = cog
        self.party_id = party.id

    async def _check_cooldown(self, interaction: discord.Interaction) -> bool:
        """True если можно жать; иначе шлёт ephemeral-сообщение и False."""
        party = self.cog.manager.get(self.party_id)
        if party is None or party.finalized:
            await interaction.response.send_message(
                "Сбор уже закрыт, кнопки больше не работают.", ephemeral=True
            )
            return False

        cooldown = timedelta(seconds=get_settings().party.button_cooldown_seconds)
        last = party.last_press.get(interaction.user.id)
        now = datetime.now(UTC)
        if last is not None:
            elapsed = now - last
            if elapsed < cooldown:
                remaining = int((cooldown - elapsed).total_seconds()) + 1
                await interaction.response.send_message(
                    f"Не дави так часто, подожди {remaining} сек.", ephemeral=True
                )
                return False

        party.last_press[interaction.user.id] = now
        return True

    @discord.ui.button(label="Готов", style=discord.ButtonStyle.success, emoji="✅")
    async def ready_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # noqa: ARG002 — обязателен по сигнатуре discord.ui
    ) -> None:
        """Кнопка «Готов» — переносит юзера в joined."""
        if not await self._check_cooldown(interaction):
            return
        await interaction.response.defer()
        updated = await self.cog.manager.mark_ready(self.party_id, interaction.user.id)
        if updated is not None:
            await self.cog._refresh_all_embeds(updated)

    @discord.ui.button(label="Не готов", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # noqa: ARG002
    ) -> None:
        """Кнопка «Не готов» — переносит в declined."""
        if not await self._check_cooldown(interaction):
            return
        await interaction.response.defer()
        updated = await self.cog.manager.mark_declined(self.party_id, interaction.user.id)
        if updated is not None:
            await self.cog._refresh_all_embeds(updated)

    async def on_timeout(self) -> None:
        """По таймауту просто отключаем кнопки на view; embed обновит финализатор."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
