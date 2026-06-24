"""View'ы модуля сбора пати.

* :class:`PartyView` — кнопки «Готов» / «Не готов» в DM (фаза сбора).
* :class:`PartyConfirmView` — кнопка «Подтверждаю» в DM (фаза чека готовности).
* :class:`PartyPreviewView` — кнопки «Опубликовать» / «Отмена» в эфемерном
  превью перед рассылкой DM.

Каждое DM-сообщение получает свой экземпляр view: timeout привязан к
``deadline`` пати. После таймаута Discord сам деактивирует кнопки клиентам;
явное обновление embed-а делает cog при финализации.

Кулдаун между нажатиями (любых кнопок) в фазе сбора — на одного пользователя
в рамках одного пати. Значение берётся из ``settings.party.button_cooldown_seconds``.
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


def _remaining_timeout(party: Party) -> float:
    """Сколько секунд осталось до закрытия сбора (минимум 1с)."""
    remaining = (party.deadline - datetime.now(UTC)).total_seconds()
    return max(1.0, remaining)


class PartyView(discord.ui.View):
    """Две кнопки в DM: «Готов» / «Не готов» для конкретного сбора."""

    def __init__(self, *, cog: PartyCog, party: Party) -> None:
        # Timeout = сколько осталось до закрытия. Discord после него отключит
        # кнопки на клиенте — больше нажать нельзя.
        super().__init__(timeout=_remaining_timeout(party))
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
            await self.cog._maybe_start_ready_check(updated)

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


class PartyConfirmView(discord.ui.View):
    """Одна кнопка «Подтверждаю» в DM для фазы чека готовности."""

    def __init__(self, *, cog: PartyCog, party: Party) -> None:
        super().__init__(timeout=_remaining_timeout(party))
        self.cog = cog
        self.party_id = party.id

    @discord.ui.button(label="Подтверждаю", style=discord.ButtonStyle.success, emoji="🟢")
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # noqa: ARG002
    ) -> None:
        """Кнопка «Подтверждаю» — закрепляет юзера в основном составе."""
        party = self.cog.manager.get(self.party_id)
        if party is None or party.finalized:
            await interaction.response.send_message(
                "Сбор уже закрыт, подтверждать нечего.", ephemeral=True
            )
            return

        await interaction.response.defer()
        updated = await self.cog.manager.confirm(self.party_id, interaction.user.id)
        if updated is not None:
            await self.cog._after_confirm(updated)

    async def on_timeout(self) -> None:
        """По таймауту гасим кнопку на клиенте."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True


class PartyPreviewView(discord.ui.View):
    """Эфемерное превью перед рассылкой: «Опубликовать» / «Отмена».

    Кнопки доступны только автору сбора. Результат пишется в :attr:`choice`
    (``"publish"`` / ``"cancel"`` / ``None`` по таймауту); публикацию делает
    вызывающий код после :meth:`discord.ui.View.wait`.
    """

    def __init__(self, *, author_id: int, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.choice: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Пускает к кнопкам только инициатора."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Это превью не для тебя.", ephemeral=True)
            return False
        return True

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="Опубликовать", style=discord.ButtonStyle.success, emoji="📣")
    async def publish_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # noqa: ARG002
    ) -> None:
        """Подтверждает публикацию сбора."""
        self.choice = "publish"
        self._disable_all()
        self.stop()
        try:
            await interaction.response.edit_message(content="Публикую сбор…", view=None)
        except discord.HTTPException as e:
            logger.warning(f"Не удалось обновить превью при публикации: {e}")

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.danger, emoji="🚫")
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # noqa: ARG002
    ) -> None:
        """Отменяет публикацию."""
        self.choice = "cancel"
        self._disable_all()
        self.stop()
        try:
            await interaction.response.edit_message(
                content="Сбор отменён, рассылки не было.", embed=None, view=None
            )
        except discord.HTTPException as e:
            logger.warning(f"Не удалось обновить превью при отмене: {e}")
