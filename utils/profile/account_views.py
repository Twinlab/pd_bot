"""Формы, предпросмотр и подтверждения управления игровыми аккаунтами."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import discord
from discord import ui

from utils.error_handler import safe_send
from utils.profile_accounts_data_manager import AccountGame, AccountLinkError
from utils.ui import colors

from .accounts import STEAM_ID_BASE, ResolvedAccount
from .builder import ProfileAccounts

if TYPE_CHECKING:
    from .views import ProfileView


def _text(value: str) -> str:
    return discord.utils.escape_mentions(
        discord.utils.escape_markdown(" ".join(value.split())[:100])
    )


def _result(title: str, description: str) -> ui.LayoutView:
    view = ui.LayoutView(timeout=None)
    view.add_item(ui.Container(ui.TextDisplay(f"### {title}\n{description}")))
    return view


def account_choices(accounts: ProfileAccounts) -> list[ResolvedAccount]:
    """Преобразует сохранённые привязки в элементы списка и подтверждения."""
    return [
        ResolvedAccount(
            "dota",
            str(pid),
            accounts.dota_names.get(pid, f"ID {pid}"),
            f"https://steamcommunity.com/profiles/{STEAM_ID_BASE + pid}",
        )
        for pid in accounts.dota_ids
    ] + [
        ResolvedAccount(
            "cs",
            account.player_id,
            account.nickname,
            f"https://www.faceit.com/en/players/{quote(account.nickname, safe='')}",
        )
        for account in accounts.faceit
    ]


class _AddAccountButton(ui.Button["ProfileView"]):
    def __init__(self, game: AccountGame, *, has_accounts: bool, full: bool) -> None:
        super().__init__(
            label="Добавить" if has_accounts else "Привязать",
            style=discord.ButtonStyle.secondary if has_accounts else discord.ButtonStyle.primary,
            custom_id=f"profile_account:add:{game}",
            disabled=full,
        )
        self.game = game

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None and await self.view.check_account_owner(interaction):
            await interaction.response.send_modal(AccountLinkModal(self.view, self.game))


class _AccountTools(ui.ActionRow["ProfileView"]):
    @ui.button(label="Отвязать аккаунт", custom_id="profile_account:remove")
    async def remove(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        if not await self.view.check_account_owner(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        accounts = await self.view.builder.build_accounts(self.view.target.id)
        choices = account_choices(accounts)
        if not choices:
            await safe_send(interaction, "Все аккаунты уже отвязаны.", ephemeral=True)
            return
        dialog = AccountRemoveView(self.view, choices)
        dialog.message = await interaction.followup.send(view=dialog, ephemeral=True, wait=True)

    @ui.button(label="Обновить", custom_id="profile_account:refresh")
    async def refresh(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await interaction.response.defer()
        await self.view.refresh_accounts()


def add_account_sections(
    container: ui.Container,
    accounts: ProfileAccounts,
    profile: ProfileView,
) -> None:
    """Добавляет секции игр с кнопками, доступными только владельцу профиля."""
    managing = profile.can_manage_accounts
    for game, title, count, lines in (
        (
            "dota",
            "Dota 2",
            len(accounts.dota_ids),
            [
                f"• [{_text(accounts.dota_names.get(pid, f'ID {pid}'))}](https://stratz.com/players/{pid})"
                for pid in accounts.dota_ids
            ],
        ),
        (
            "cs",
            "Counter-Strike 2 · FACEIT",
            len(accounts.faceit),
            [
                f"• [{_text(account.nickname)}](https://www.faceit.com/en/players/{quote(account.nickname, safe='')})"
                for account in accounts.faceit
            ],
        ),
    ):
        body = "\n".join(lines) if lines else "Аккаунты пока не привязаны."
        if managing:
            limit = profile.account_service.settings.limits.links_max_per_user
            section = ui.Section(
                f"### {title}\n{body}\n-# {count} из {limit} аккаунтов",
                accessory=_AddAccountButton(game, has_accounts=bool(count), full=count >= limit),
            )
            container.add_item(section)
        else:
            container.add_item(ui.TextDisplay(f"### {title}\n{body}"))
        if game == "dota":
            container.add_item(ui.Separator())
    if managing and (accounts.dota_ids or accounts.faceit):
        container.add_item(_AccountTools())


class AccountLinkModal(ui.Modal):
    """Одно поле для ссылки, ID Dota или ника FACEIT."""

    def __init__(self, profile: ProfileView, game: AccountGame) -> None:
        super().__init__(
            title="Привязать Dota 2" if game == "dota" else "Привязать FACEIT", timeout=300
        )
        self.profile = profile
        self.game = game
        self.account_input: ui.TextInput[AccountLinkModal] = ui.TextInput(
            placeholder="steamcommunity.com/id/… или ID Dota"
            if game == "dota"
            else "Ссылка Steam / FACEIT или ник FACEIT",
            max_length=300,
        )
        self.add_item(
            ui.Label(
                text="Ссылка на профиль или ID"
                if game == "dota"
                else "Ссылка на профиль или ник FACEIT",
                description="Можно вставить ссылку Steam, FACEIT, Dotabuff или STRATZ.",
                component=self.account_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Показывает найденный аккаунт без автоматического сохранения."""
        if not await self.profile.check_account_owner(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            account = await self.profile.account_service.resolve(
                self.account_input.value, self.game
            )
        except AccountLinkError as error:
            await safe_send(interaction, str(error), ephemeral=True)
            return
        dialog = AccountConfirmView(self.profile, account)
        dialog.message = await interaction.followup.send(view=dialog, ephemeral=True, wait=True)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: ui.Item[Any] | None = None
    ) -> None:
        """Передаёт неожиданные ошибки общему обработчику профиля."""
        await self.profile.on_error(interaction, error, item or self.account_input)


class _AccountDialog(ui.LayoutView):
    def __init__(self, profile: ProfileView) -> None:
        super().__init__(timeout=300)
        self.profile = profile
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяет владельца и срок действия родительского профиля."""
        if self.is_finished():
            await safe_send(
                interaction, "Подтверждение устарело. Откройте форму заново.", ephemeral=True
            )
            return False
        return await self.profile.check_account_owner(interaction)

    async def on_timeout(self) -> None:
        """Отключает незавершённое подтверждение, не меняя привязки."""
        self.stop()
        for item in self.walk_children():
            if isinstance(item, (ui.Button, ui.Select)) and getattr(item, "url", None) is None:
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: ui.Item[Any]
    ) -> None:
        """Передаёт ошибки общему обработчику профиля."""
        await self.profile.on_error(interaction, error, item)


class _ConfirmActions(ui.ActionRow["AccountConfirmView"]):
    @ui.button(
        label="Привязать", style=discord.ButtonStyle.success, custom_id="profile_account:confirm"
    )
    async def confirm(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await self.view.confirm(interaction)

    @ui.button(label="Отмена", custom_id="profile_account:cancel")
    async def cancel(self, interaction: discord.Interaction, _button: ui.Button) -> None:
        await self.view.cancel(interaction)


class AccountConfirmView(_AccountDialog):
    """Подтверждение конкретной привязки или отвязки."""

    def __init__(
        self, profile: ProfileView, account: ResolvedAccount, *, remove: bool = False
    ) -> None:
        super().__init__(profile)
        self.account = account
        self.remove = remove
        self._lock = asyncio.Lock()
        self._completed = False
        title = "Отвязать аккаунт?" if remove else "Проверьте аккаунт"
        game_name = "Dota 2" if account.game == "dota" else "FACEIT · CS2"
        container: ui.Container = ui.Container(
            accent_colour=colors.WARNING if remove else colors.BRAND
        )
        text = f"### {title}\n**{_text(account.name)}**\n{game_name}"
        if account.game == "dota":
            text += f" · ID {account.identifier}"
        if account.avatar:
            container.add_item(ui.Section(text, accessory=ui.Thumbnail(account.avatar)))
        else:
            container.add_item(ui.TextDisplay(text))
        container.add_item(ui.ActionRow(ui.Button(label="Открыть профиль", url=account.url)))
        container.add_item(
            ui.TextDisplay(
                "Аккаунт исчезнет из вашего профиля. Его можно привязать снова."
                if remove
                else "Проверьте профиль по ссылке и подтвердите привязку."
            )
        )
        actions = _ConfirmActions()
        if remove:
            actions.confirm.label = "Отвязать"
            actions.confirm.style = discord.ButtonStyle.danger
        container.add_item(actions)
        self.add_item(container)

    async def confirm(self, interaction: discord.Interaction) -> None:
        """Выполняет подтверждённое действие один раз и обновляет исходный профиль."""
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self._lock:
            if self._completed:
                return
            try:
                if self.remove:
                    await self.profile.account_service.remove(self.profile.target.id, self.account)
                else:
                    await self.profile.account_service.save(self.profile.target.id, self.account)
            except AccountLinkError as error:
                await safe_send(interaction, str(error), ephemeral=True)
                return
            self._completed = True
            self.stop()
            title = "Аккаунт отвязан" if self.remove else "Аккаунт привязан"
            try:
                await interaction.edit_original_response(
                    view=_result(title, _text(self.account.name))
                )
            finally:
                await self.profile.refresh_accounts()

    async def cancel(self, interaction: discord.Interaction) -> None:
        """Закрывает подтверждение без изменения аккаунтов."""
        if not await self.profile.check_account_owner(interaction):
            return
        await interaction.response.defer()
        async with self._lock:
            if self._completed:
                return
            self._completed = True
            self.stop()
            await interaction.edit_original_response(
                view=_result("Отменено", "Привязки не изменились.")
            )


class _RemoveSelect(ui.Select["AccountRemoveView"]):
    def __init__(self, accounts: list[ResolvedAccount]) -> None:
        super().__init__(
            placeholder="Выберите аккаунт для отвязки",
            custom_id="profile_account:remove_select",
            options=[
                discord.SelectOption(
                    label=("Dota 2 · " if account.game == "dota" else "FACEIT · ")
                    + account.name[:80],
                    value=str(index),
                    description=f"ID {account.identifier}"[:100],
                )
                for index, account in enumerate(accounts)
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is None or not await self.view.profile.check_account_owner(interaction):
            return
        account = self.view.accounts[int(self.values[0])]
        confirmation = AccountConfirmView(self.view.profile, account, remove=True)
        confirmation.message = self.view.message
        await interaction.response.edit_message(view=confirmation)
        self.view.stop()


class AccountRemoveView(_AccountDialog):
    """Выбор одной привязки перед подтверждением отвязки."""

    def __init__(self, profile: ProfileView, accounts: list[ResolvedAccount]) -> None:
        super().__init__(profile)
        self.accounts = accounts
        self.add_item(
            ui.Container(
                ui.TextDisplay(
                    "### Отвязать аккаунт\nВыберите аккаунт. На следующем шаге будет подтверждение."
                ),
                ui.ActionRow(_RemoveSelect(accounts)),
            )
        )
