"""View'ы модуля сбора пати.

* :class:`PartyView` — кнопки «Готов» / «Не готов» в DM (фаза сбора).
* :class:`PartyConfirmView` — кнопка «Подтверждаю» в DM (фаза чека готовности).
* :class:`PartyBuilderView` — пошаговый мастер ``/party`` (роль → параметры →
  превью) в эфемерном сообщении.

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


class _RoleSelect(discord.ui.Select["PartyBuilderView"]):
    """Шаг 1 — выпадающий список доступных игровых ролей."""

    def __init__(self, builder: PartyBuilderView, roles: list[discord.Role]) -> None:
        options = [
            discord.SelectOption(label=role.name[:100], value=str(role.id)) for role in roles[:25]
        ]
        super().__init__(
            placeholder="Шаг 1: выбери роль", min_values=1, max_values=1, options=options, row=0
        )
        self._builder = builder

    async def callback(self, interaction: discord.Interaction) -> None:
        self._builder.role_id = int(self.values[0])
        await self._builder.go_to_params(interaction)


class _ParamsButton(discord.ui.Button["PartyBuilderView"]):
    """Шаг 2 — открывает модалку свободного ввода параметров."""

    def __init__(self, builder: PartyBuilderView) -> None:
        super().__init__(label="Параметры", style=discord.ButtonStyle.primary, emoji="✏️", row=0)
        self._builder = builder

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(_PartyParamsModal(self._builder))


class _PublishButton(discord.ui.Button["PartyBuilderView"]):
    """Шаг 3 — публикует сбор."""

    def __init__(self, builder: PartyBuilderView) -> None:
        super().__init__(label="Опубликовать", style=discord.ButtonStyle.success, emoji="📣", row=0)
        self._builder = builder

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._builder.publish(interaction)


class _CancelButton(discord.ui.Button["PartyBuilderView"]):
    """Закрывает мастер без публикации (доступна на любом шаге)."""

    def __init__(self, builder: PartyBuilderView) -> None:
        super().__init__(label="Отмена", style=discord.ButtonStyle.danger, emoji="🚫", row=1)
        self._builder = builder

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._builder.cancel(interaction)


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
        await self._builder.go_to_preview(interaction)


class PartyBuilderView(discord.ui.View):
    """Пошаговый мастер сбора пати (команда ``/party``).

    Шаги переключаются редактированием одного эфемерного сообщения:
    ``role`` (выпадушка ролей) → ``params`` (модалка свободного ввода времени,
    состава и комментария) → ``preview`` (готовый embed + «Опубликовать»).
    Картинка приходит параметром команды. Публикацию делает
    ``cog._create_and_broadcast``.
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

        self.step = "role"
        self.role_id: int | None = None
        self.minutes: int | None = None
        self.count: int | None = None
        self.comment: str = ""

        self._show_role_step()

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
        """Пускает к мастеру только автора."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Это не твоя форма.", ephemeral=True)
            return False
        return True

    def _show_role_step(self) -> None:
        self.clear_items()
        self.add_item(_RoleSelect(self, list(self.roles.values())))
        self.add_item(_CancelButton(self))

    def _show_params_step(self) -> None:
        self.clear_items()
        self.add_item(_ParamsButton(self))
        self.add_item(_CancelButton(self))

    def _show_preview_step(self) -> None:
        self.clear_items()
        self.add_item(_PublishButton(self))
        self.add_item(_CancelButton(self))

    def build_embed(self) -> discord.Embed:
        """Embed под текущий шаг мастера."""
        if self.step == "preview":
            role = self.roles.get(self.role_id) if self.role_id else None
            if role is not None and self.minutes is not None and self.count is not None:
                embed = self.cog.build_party_preview_embed(
                    role=role,
                    initiator=self.initiator,
                    duration=timedelta(minutes=self.minutes),
                    count=self.count,
                    comment=self.comment,
                    image_url=self.image_url,
                )
                embed.set_author(name="Шаг 3/3 — так будет выглядеть сбор")
                return embed

        if self.step == "params":
            role = self.roles.get(self.role_id) if self.role_id else None
            embed = discord.Embed(
                title="Сбор пати — шаг 2/3",
                description="Жми «Параметры» и заполни время, состав и комментарий.",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="Роль", value=role.mention if role else "—", inline=True)
            return embed

        return discord.Embed(
            title="Сбор пати — шаг 1/3",
            description="Выбери игровую роль из списка.",
            color=discord.Color.blurple(),
        )

    async def _render(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except discord.HTTPException as e:
            logger.warning(f"Не удалось обновить мастер сбора пати: {e}")

    async def go_to_params(self, interaction: discord.Interaction) -> None:
        """Переход на шаг ввода параметров."""
        self.step = "params"
        self._show_params_step()
        await self._render(interaction)

    async def go_to_preview(self, interaction: discord.Interaction) -> None:
        """Переход на шаг превью после успешного ввода параметров."""
        self.step = "preview"
        self._show_preview_step()
        await self._render(interaction)

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True

    async def publish(self, interaction: discord.Interaction) -> None:
        """Публикует сбор по кнопке «Опубликовать»."""
        role = self.roles.get(self.role_id) if self.role_id else None
        channel = interaction.channel
        if (
            role is None
            or self.minutes is None
            or self.count is None
            or interaction.guild is None
            or not isinstance(channel, discord.abc.Messageable)
        ):
            await interaction.response.send_message(
                "Не получилось определить роль, параметры или канал.", ephemeral=True
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

    async def cancel(self, interaction: discord.Interaction) -> None:
        """Закрывает мастер без публикации."""
        self._disable_all()
        self.stop()
        try:
            await interaction.response.edit_message(
                content="Сборка отменена.", embed=None, view=None
            )
        except discord.HTTPException as e:
            logger.warning(f"Не удалось закрыть мастер сбора пати: {e}")
