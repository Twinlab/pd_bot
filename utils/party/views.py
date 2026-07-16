"""View'ы и модалка модуля сбора пати (Components V2).

* :class:`PartyView` — карточка сбора + кнопки «Готов» / «Не готов» в DM
  (фаза сбора). Контент и кнопки живут в одном ``LayoutView``.
* :class:`PartyConfirmView` — карточка + кнопка «Подтверждаю» в DM (фаза чека).
* :class:`PartySetupModal` — единая модалка ``/party`` (Modal v2): роль + время +
  состав + коммент в одном окне.
* :class:`PartyPublishView` — превью сбора с кнопками «Опубликовать / Изменить /
  Отмена» (CV2).

Каждое DM-сообщение получает свой экземпляр view: timeout привязан к
``deadline`` пати. После таймаута Discord сам деактивирует кнопки клиентам;
явное обновление карточки делает cog при финализации.

Кулдаун между нажатиями (любых кнопок) в фазе сбора — на одного пользователя
в рамках одного пати. Значение берётся из ``settings.party.button_cooldown_seconds``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord

from config import get_settings
from utils.ui import colors

if TYPE_CHECKING:
    from cogs.party import PartyCog
    from utils.party.manager import Party

logger = logging.getLogger("bot.utils.party_views")


def _remaining_timeout(party: Party) -> float:
    """Сколько секунд осталось до закрытия сбора (минимум 1с)."""
    remaining = (party.deadline - datetime.now(UTC)).total_seconds()
    return max(1.0, remaining)


def _notice_view(text: str) -> discord.ui.LayoutView:
    """Минимальный CV2-вью с одной строкой (служебные «Создаю сбор…» / «Отменено»)."""
    view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=None)
    container: discord.ui.Container = discord.ui.Container(accent_colour=colors.NEUTRAL)
    container.add_item(discord.ui.TextDisplay(text))
    view.add_item(container)
    return view


class _ReadyDeclineRow(discord.ui.ActionRow["PartyView"]):
    """Ряд DM-кнопок фазы сбора: «Готов» / «Не готов»."""

    @discord.ui.button(label="Готов", style=discord.ButtonStyle.success, emoji="✅")
    async def ready(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_ready(interaction)

    @discord.ui.button(label="Не готов", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_decline(interaction)


class PartyView(discord.ui.LayoutView):
    """CV2-карточка сбора + кнопки «Готов» / «Не готов» в одном сообщении."""

    def __init__(self, *, cog: PartyCog, party: Party) -> None:
        # Timeout = сколько осталось до закрытия. Discord после него отключит
        # кнопки на клиенте — больше нажать нельзя.
        super().__init__(timeout=_remaining_timeout(party))
        self.cog = cog
        self.party_id = party.id
        container = cog._build_container(party)
        container.add_item(_ReadyDeclineRow())
        self.add_item(container)

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

    async def handle_ready(self, interaction: discord.Interaction) -> None:
        """Кнопка «Готов» — переносит юзера в joined."""
        if not await self._check_cooldown(interaction):
            return
        await interaction.response.defer()
        updated = await self.cog.manager.mark_ready(self.party_id, interaction.user.id)
        if updated is not None:
            await self.cog._refresh_all_embeds(updated)
            await self.cog._maybe_start_ready_check(updated)

    async def handle_decline(self, interaction: discord.Interaction) -> None:
        """Кнопка «Не готов» — переносит в declined."""
        if not await self._check_cooldown(interaction):
            return
        await interaction.response.defer()
        updated = await self.cog.manager.mark_declined(self.party_id, interaction.user.id)
        if updated is not None:
            await self.cog._refresh_all_embeds(updated)

    async def on_timeout(self) -> None:
        """По таймауту гасим кнопки на view; карточку обновит финализатор."""
        for child in self.walk_children():
            if isinstance(child, discord.ui.Button):
                child.disabled = True


class _ConfirmRow(discord.ui.ActionRow["PartyConfirmView"]):
    """Ряд DM-кнопки фазы чека: «Подтверждаю»."""

    @discord.ui.button(label="Подтверждаю", style=discord.ButtonStyle.success, emoji="🟢")
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_confirm(interaction)


class PartyConfirmView(discord.ui.LayoutView):
    """CV2-карточка + кнопка «Подтверждаю» в DM для фазы чека готовности."""

    def __init__(self, *, cog: PartyCog, party: Party) -> None:
        super().__init__(timeout=_remaining_timeout(party))
        self.cog = cog
        self.party_id = party.id
        container = cog._build_container(party)
        container.add_item(_ConfirmRow())
        self.add_item(container)

    async def handle_confirm(self, interaction: discord.Interaction) -> None:
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
        for child in self.walk_children():
            if isinstance(child, discord.ui.Button):
                child.disabled = True


@dataclass(slots=True)
class _PartyDraft:
    """Снимок параметров сбора между сабмитом модалки и публикацией."""

    role_id: int
    minutes: int
    count: int
    comment: str


def _count_options(default_count: int | None = None) -> list[discord.SelectOption]:
    """Опции размера состава от ``min_count`` до ``max_count`` включительно.

    Срез до 25 — жёсткий лимит опций у Discord-``Select`` (как и у списка ролей).
    """
    s = get_settings().party
    chosen = default_count if default_count is not None else s.max_count
    return [
        discord.SelectOption(label=f"{n} чел.", value=str(n), default=(n == chosen))
        for n in range(s.min_count, s.max_count + 1)
    ][:25]


class PartySetupModal(discord.ui.Modal, title="Сбор пати"):
    """Единая модалка сбора (Modal v2): роль + время + состав + коммент.

    Заменяет трёхшаговый мастер: роль и состав — ``Select`` (валидны по
    построению), время — ``TextInput`` (нужны произвольные минуты),
    комментарий — ``TextInput``. Состав именно ``Select``, а не ``RadioGroup``:
    у радиогруппы жёсткий лимит 2–10 опций, а состав бывает шире (min..max_count).
    """

    def __init__(
        self,
        *,
        cog: PartyCog,
        initiator: discord.Member,
        roles: list[discord.Role],
        image_url: str | None,
        defaults: _PartyDraft | None = None,
    ) -> None:
        super().__init__()
        self._cog = cog
        self._initiator = initiator
        self._roles = {r.id: r for r in roles}
        self._image_url = image_url
        s = get_settings().party

        self._role_select: discord.ui.Select[PartySetupModal] = discord.ui.Select(
            placeholder="Выбери игровую роль",
            required=True,
            options=[
                discord.SelectOption(
                    label=r.name[:100],
                    value=str(r.id),
                    default=(defaults is not None and defaults.role_id == r.id),
                )
                for r in roles[:25]
            ],
        )
        self._duration_input: discord.ui.TextInput[PartySetupModal] = discord.ui.TextInput(
            required=True,
            max_length=4,
            placeholder="например, 30",
            default=str(defaults.minutes) if defaults else None,
        )
        self._size_select: discord.ui.Select[PartySetupModal] = discord.ui.Select(
            placeholder="Сколько человек",
            required=True,
            options=_count_options(defaults.count if defaults else None),
        )
        self._comment_input: discord.ui.TextInput[PartySetupModal] = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            placeholder="Что собираем, во сколько, условия…",
            default=(defaults.comment if defaults else None) or None,
        )

        self.add_item(
            discord.ui.Label(
                text="Роль", description="На кого собираем стак", component=self._role_select
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Через сколько закрыть (минут)",
                description=f"От {s.min_duration_minutes} до {s.max_duration_minutes}",
                component=self._duration_input,
            )
        )
        self.add_item(
            discord.ui.Label(text="Размер состава (с тобой)", component=self._size_select)
        )
        self.add_item(
            discord.ui.Label(
                text="Комментарий",
                description="Что собираем, во сколько, условия",
                component=self._comment_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Валидирует минуты, собирает черновик и показывает превью с публикацией."""
        s = get_settings().party
        try:
            minutes = int((self._duration_input.value or "").strip())
        except ValueError:
            await interaction.response.send_message("Время — это число минут.", ephemeral=True)
            return
        if not (s.min_duration_minutes <= minutes <= s.max_duration_minutes):
            await interaction.response.send_message(
                f"Время — от {s.min_duration_minutes} до {s.max_duration_minutes} минут.",
                ephemeral=True,
            )
            return

        size_values = self._size_select.values
        draft = _PartyDraft(
            role_id=int(self._role_select.values[0]),
            minutes=minutes,
            count=int(size_values[0]) if size_values else s.max_count,
            comment=(self._comment_input.value or "").strip(),
        )
        if self._roles.get(draft.role_id) is None:
            await interaction.response.send_message("Роль не найдена.", ephemeral=True)
            return

        await interaction.response.send_message(
            view=PartyPublishView(
                cog=self._cog,
                initiator=self._initiator,
                roles=list(self._roles.values()),
                image_url=self._image_url,
                draft=draft,
            ),
            ephemeral=True,
        )


class _PublishRow(discord.ui.ActionRow["PartyPublishView"]):
    """Ряд кнопок превью: опубликовать / изменить / отмена."""

    @discord.ui.button(label="Опубликовать", style=discord.ButtonStyle.success, emoji="📣")
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_publish(interaction)

    @discord.ui.button(label="Изменить", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def edit(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_edit(interaction)

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.danger, emoji="🚫")
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_cancel(interaction)


class PartyPublishView(discord.ui.LayoutView):
    """Превью сбора (CV2): опубликовать / изменить (переоткрыть модалку) / отмена."""

    def __init__(
        self,
        *,
        cog: PartyCog,
        initiator: discord.Member,
        roles: list[discord.Role],
        image_url: str | None,
        draft: _PartyDraft,
    ) -> None:
        super().__init__(timeout=300.0)
        self._cog = cog
        self._initiator = initiator
        self._roles = roles
        self._image_url = image_url
        self._draft = draft

        role = next((r for r in roles if r.id == draft.role_id), None)
        container = cog.build_party_preview_container(
            role=role,
            initiator=initiator,
            duration=timedelta(minutes=draft.minutes),
            count=draft.count,
            comment=draft.comment,
            image_url=image_url,
        )
        container.add_item(_PublishRow())
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Пускает к превью только автора."""
        if interaction.user.id != self._initiator.id:
            await interaction.response.send_message("Это не твоя форма.", ephemeral=True)
            return False
        return True

    async def handle_publish(self, interaction: discord.Interaction) -> None:
        """Публикует сбор по кнопке «Опубликовать»."""
        role = next((r for r in self._roles if r.id == self._draft.role_id), None)
        channel = interaction.channel
        if (
            role is None
            or interaction.guild is None
            or not isinstance(channel, discord.abc.Messageable)
        ):
            await interaction.response.send_message(
                "Не удалось определить роль или канал.", ephemeral=True
            )
            return
        self.stop()
        await interaction.response.edit_message(view=_notice_view("Создаю сбор…"))
        await self._cog._create_and_broadcast(
            guild=interaction.guild,
            channel=channel,
            role=role,
            initiator=self._initiator,
            duration=timedelta(minutes=self._draft.minutes),
            count=self._draft.count,
            comment=self._draft.comment,
            image_url=self._image_url,
        )

    async def handle_edit(self, interaction: discord.Interaction) -> None:
        """Переоткрывает модалку с уже заполненными значениями."""
        await interaction.response.send_modal(
            PartySetupModal(
                cog=self._cog,
                initiator=self._initiator,
                roles=self._roles,
                image_url=self._image_url,
                defaults=self._draft,
            )
        )

    async def handle_cancel(self, interaction: discord.Interaction) -> None:
        """Закрывает превью без публикации."""
        self.stop()
        try:
            await interaction.response.edit_message(view=_notice_view("Сборка отменена."))
        except discord.HTTPException as e:
            logger.warning(f"Не удалось закрыть превью сбора пати: {e}")
