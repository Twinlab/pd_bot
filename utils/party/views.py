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


class _RoleSelect(discord.ui.Select["PartyBuilderView"]):
    """Выпадающий список доступных игровых ролей."""

    def __init__(self, builder: PartyBuilderView, roles: list[discord.Role]) -> None:
        options = [
            discord.SelectOption(label=role.name[:100], value=str(role.id)) for role in roles[:25]
        ]
        super().__init__(
            placeholder="Выбери роль", min_values=1, max_values=1, options=options, row=0
        )
        self._builder = builder

    async def callback(self, interaction: discord.Interaction) -> None:
        self._builder.role_id = int(self.values[0])
        await self._builder.refresh(interaction)


class _PartyParamsModal(discord.ui.Modal, title="Параметры сбора"):
    """Модалка свободного ввода: время, размер состава и комментарий."""

    minutes_input: discord.ui.TextInput[_PartyParamsModal] = discord.ui.TextInput(
        label="Через сколько закрыть (минут)",
        required=True,
        max_length=4,
        placeholder="например, 30",
    )
    count_input: discord.ui.TextInput[_PartyParamsModal] = discord.ui.TextInput(
        label="Сколько человек в состав (с тобой)",
        required=True,
        max_length=3,
        placeholder="например, 5",
    )
    comment_input: discord.ui.TextInput[_PartyParamsModal] = discord.ui.TextInput(
        label="Комментарий",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
        placeholder="Что собираем, во сколько, какие условия…",
    )

    def __init__(self, builder: PartyBuilderView) -> None:
        super().__init__()
        self._builder = builder
        if builder.minutes is not None:
            self.minutes_input.default = str(builder.minutes)
        if builder.count is not None:
            self.count_input.default = str(builder.count)
        if builder.comment:
            self.comment_input.default = builder.comment

    async def on_submit(self, interaction: discord.Interaction) -> None:
        error = self._builder.apply_params(
            minutes_raw=str(self.minutes_input.value),
            count_raw=str(self.count_input.value),
            comment=str(self.comment_input.value or ""),
        )
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await self._builder.refresh(interaction)


class PartyBuilderView(discord.ui.View):
    """Эфемерная панель сборки пати на меню (команда ``/party_beta``).

    Роль выбирается выпадушкой; время, размер состава и комментарий вводятся
    свободным текстом в модалке «Параметры»; картинка приходит параметром
    команды. По кнопке «Создать» дёргается ``cog._create_and_broadcast``.
    """

    def __init__(
        self,
        *,
        cog: PartyCog,
        author_id: int,
        initiator: discord.Member,
        roles: list[discord.Role],
        image_url: str | None,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id
        self.initiator = initiator
        self.roles = {role.id: role for role in roles}
        self.image_url = image_url

        self.role_id: int | None = None
        self.minutes: int | None = None
        self.count: int | None = None
        self.comment: str = ""

        self.add_item(_RoleSelect(self, roles))

    def apply_params(self, *, minutes_raw: str, count_raw: str, comment: str) -> str | None:
        """Валидирует и применяет ввод из модалки.

        Возвращает текст ошибки (для ephemeral-ответа) или ``None`` при успехе.
        """
        settings = get_settings().party
        try:
            minutes = int(minutes_raw.strip())
        except ValueError:
            return "Время должно быть числом минут (например, 30)."
        if not (settings.min_duration_minutes <= minutes <= settings.max_duration_minutes):
            return (
                f"Время — от {settings.min_duration_minutes} "
                f"до {settings.max_duration_minutes} минут."
            )

        try:
            count = int(count_raw.strip())
        except ValueError:
            return "Размер состава должен быть числом (например, 5)."
        if not (settings.min_count <= count <= settings.max_count):
            return f"Состав — от {settings.min_count} до {settings.max_count} человек."

        self.minutes = minutes
        self.count = count
        self.comment = comment.strip()
        return None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Пускает к панели только автора."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Это не твоя панель.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        """Сводка текущего выбора панели."""
        role = self.roles.get(self.role_id) if self.role_id else None
        embed = discord.Embed(
            title="Сборка пати (бета)",
            description="Выбери роль, жми «Параметры» (время/состав/коммент), затем «Создать».",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Роль", value=role.mention if role else "_не выбрана_", inline=True)
        embed.add_field(
            name="Закрытие",
            value=f"{self.minutes} мин" if self.minutes else "_не выбрано_",
            inline=True,
        )
        embed.add_field(
            name="Состав",
            value=f"{self.count} чел." if self.count else "_не выбран_",
            inline=True,
        )
        embed.add_field(name="Комментарий", value=self.comment or "_пусто_", inline=False)
        embed.add_field(name="Картинка", value="есть" if self.image_url else "нет", inline=True)
        return embed

    async def refresh(self, interaction: discord.Interaction) -> None:
        """Перерисовывает панель с актуальным выбором."""
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except discord.HTTPException as e:
            logger.warning(f"Не удалось обновить панель сборки пати: {e}")

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True

    @discord.ui.button(label="Параметры", style=discord.ButtonStyle.secondary, emoji="✏️", row=1)
    async def params_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # noqa: ARG002
    ) -> None:
        """Открывает модалку ввода времени, состава и комментария."""
        await interaction.response.send_modal(_PartyParamsModal(self))

    @discord.ui.button(label="Создать", style=discord.ButtonStyle.success, emoji="📣", row=1)
    async def create_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # noqa: ARG002
    ) -> None:
        """Валидирует выбор и публикует сбор."""
        if self.role_id is None or self.minutes is None or self.count is None:
            await interaction.response.send_message(
                "Сначала выбери роль и заполни «Параметры» (время и состав).", ephemeral=True
            )
            return
        role = self.roles.get(self.role_id)
        channel = interaction.channel
        if (
            role is None
            or interaction.guild is None
            or not isinstance(channel, discord.abc.Messageable)
        ):
            await interaction.response.send_message(
                "Не получилось определить роль или канал.", ephemeral=True
            )
            return

        self._disable_all()
        self.stop()
        await interaction.response.edit_message(content="Создаю сбор…", embed=None, view=None)
        await self.cog._create_and_broadcast(
            guild=interaction.guild,
            channel=channel,
            role=role,
            initiator=self.initiator,
            duration=timedelta(minutes=self.minutes),
            count=self.count,
            comment=self.comment,
            image_url=self.image_url,
        )

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.danger, emoji="🚫", row=1)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,  # noqa: ARG002
    ) -> None:
        """Закрывает панель без публикации."""
        self._disable_all()
        self.stop()
        try:
            await interaction.response.edit_message(
                content="Сборка отменена.", embed=None, view=None
            )
        except discord.HTTPException as e:
            logger.warning(f"Не удалось закрыть панель сборки пати: {e}")
