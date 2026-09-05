"""Единый интерактивный профиль пользователя."""

from __future__ import annotations

import logging
from typing import Any, Protocol, cast

import discord
from discord import app_commands
from discord.ext import commands

from utils.activity.helpers import is_application
from utils.error_handler import command_error_handler, safe_send_error
from utils.profile import (
    ProfileMatchGame,
    ProfilePeriod,
    ProfileStatsBuilder,
    ProfileView,
)
from utils.profile.accounts import ProfileAccountService

logger = logging.getLogger("bot.cogs.profile")


class _LastMatchSender(Protocol):
    async def send_last_match(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
    ) -> None: ...


class _EphemeralInteractionContext:
    """Минимальный Context-адаптер для существующих рендереров матчей."""

    def __init__(self, bot: commands.Bot, interaction: discord.Interaction) -> None:
        self.bot = bot
        self.author = interaction.user
        self._interaction = interaction

    async def send(self, content: str | None = None, **kwargs: Any) -> Any:
        """Отправляет результат только нажавшему кнопку пользователю."""
        kwargs["ephemeral"] = True
        kwargs["wait"] = True
        return await self._interaction.followup.send(content, **kwargs)


class ProfileCog(commands.Cog):
    """Команда профиля и контекстное меню пользователя."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.builder = ProfileStatsBuilder()
        self.account_service = ProfileAccountService(bot.settings)
        self.profile_menu = app_commands.ContextMenu(
            name="Профиль",
            callback=self.profile_context_menu,
        )
        self.bot.tree.add_command(self.profile_menu)

    async def cog_unload(self) -> None:
        """Удаляет контекстное меню при выгрузке кога."""
        self.bot.tree.remove_command(self.profile_menu.name, type=self.profile_menu.type)
        await self.account_service.close()

    @staticmethod
    def _current_game(member: discord.Member) -> str | None:
        for activity in member.activities:
            if activity.type == discord.ActivityType.playing and activity.name:
                return activity.name
        return None

    @staticmethod
    def _eligible_user_ids(guild: discord.Guild) -> set[int]:
        return {
            member.id for member in guild.members if not member.bot and not is_application(member)
        }

    async def build_view(
        self,
        *,
        target: discord.Member,
        period: ProfilePeriod,
        viewer_id: int | None = None,
        public: bool = False,
    ) -> ProfileView:
        """Собирает начальное состояние профиля."""
        eligible_user_ids = self._eligible_user_ids(target.guild)
        stats = await self.builder.build_stats(
            user_id=target.id,
            period=period,
            eligible_user_ids=eligible_user_ids,
            current_game=self._current_game(target),
        )
        return ProfileView(
            target=target,
            builder=self.builder,
            stats=stats,
            eligible_user_ids=eligible_user_ids,
            match_callback=self._send_profile_match,
            viewer_id=viewer_id,
            account_service=self.account_service,
            public=public,
        )

    async def _send_profile_match(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        game: ProfileMatchGame,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        cog_name = "LastMatchCog" if game == "dota" else "CsLastMatchCog"
        sender = cast(_LastMatchSender | None, self.bot.get_cog(cog_name))
        if sender is None:
            await interaction.followup.send(
                "Просмотр матчей сейчас недоступен.",
                ephemeral=True,
            )
            return

        context = cast(
            commands.Context,
            _EphemeralInteractionContext(self.bot, interaction),
        )
        await sender.send_last_match(context, target)

    async def send_from_interaction(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        period: ProfilePeriod,
        *,
        ephemeral: bool,
    ) -> None:
        """Отправляет профиль с выбранной видимостью."""
        await interaction.response.defer(ephemeral=ephemeral)
        view = await self.build_view(
            target=target,
            period=period,
            viewer_id=interaction.user.id,
            public=not ephemeral,
        )
        message = await interaction.followup.send(
            view=view,
            ephemeral=ephemeral,
            wait=True,
        )
        view.message = cast(discord.Message, message)

    @app_commands.command(
        name="profile",
        description="Показать интерактивный профиль участника.",
    )
    @app_commands.guild_only()
    @app_commands.describe(user="Чей профиль показать (по умолчанию — ваш).")
    @command_error_handler
    async def profile(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        """Открывает профиль за текущий месяц."""
        target = user or interaction.user
        if not isinstance(target, discord.Member):
            await safe_send_error(interaction, "Профиль доступен только участникам сервера.")
            return
        await self.send_from_interaction(
            interaction, target, ProfilePeriod.current_month(), ephemeral=False
        )

    @app_commands.guild_only()
    async def profile_context_menu(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ) -> None:
        """Открывает профиль выбранного участника эфемерно."""
        await self.send_from_interaction(
            interaction,
            member,
            ProfilePeriod.current_month(),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Загружает профиль в бота."""
    await bot.add_cog(ProfileCog(bot))
    logger.info("ProfileCog успешно загружен.")
