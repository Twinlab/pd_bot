"""Persistent-кнопки выдачи ролей (замена эмодзи-реакций).

Кнопка :class:`RoleButton` — это ``discord.ui.DynamicItem``: ``role_id`` зашит
в ``custom_id`` (``rr:role:<id>``), поэтому одна регистрация
``bot.add_dynamic_items(RoleButton)`` оживляет кнопки на всех ролевых
сообщениях даже после рестарта бота — без хранения отдельных view.

Нажатие переключает роль: есть — снимаем, нет — выдаём.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord import ui

logger = logging.getLogger("bot.utils.role_reaction_views")

CUSTOM_ID_TEMPLATE = re.compile(r"rr:role:(?P<role_id>\d+)")

# Discord-лимит: максимум 25 интерактивных компонентов на сообщение.
MAX_BUTTONS = 25


def parse_emoji(raw: str) -> discord.PartialEmoji | str | None:
    """Преобразует хранимый эмодзи в формат для кнопки.

    В БД эмодзи лежит как unicode (``✅``) или как ``name:id`` для кастомных.
    """
    if not raw:
        return None
    name, sep, id_str = raw.rpartition(":")
    if sep and id_str.isdigit():
        return discord.PartialEmoji(name=name, id=int(id_str))
    return raw


class RoleButton(ui.DynamicItem[ui.Button], template=CUSTOM_ID_TEMPLATE):
    """Кнопка-переключатель роли; ``role_id`` восстанавливается из ``custom_id``."""

    def __init__(
        self,
        role_id: int,
        *,
        label: str | None = None,
        emoji: discord.PartialEmoji | str | None = None,
    ) -> None:
        self.role_id = role_id
        super().__init__(
            ui.Button(
                style=discord.ButtonStyle.secondary,
                label=label,
                emoji=emoji,
                custom_id=f"rr:role:{role_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: ui.Item[Any],
        match: re.Match[str],
        /,
    ) -> RoleButton:
        return cls(int(match["role_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        """Переключает роль у нажавшего: есть — снимает, нет — выдаёт."""
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return

        role = guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message("Роль больше не существует.", ephemeral=True)
            return

        no_mentions = discord.AllowedMentions.none()
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Роль по кнопке")
                await interaction.response.send_message(
                    f"Снял роль {role.mention}.", ephemeral=True, allowed_mentions=no_mentions
                )
            else:
                await member.add_roles(role, reason="Роль по кнопке")
                await interaction.response.send_message(
                    f"Выдал роль {role.mention}.", ephemeral=True, allowed_mentions=no_mentions
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "У меня нет прав на эту роль — проверь, что моя роль выше неё.", ephemeral=True
            )
        except discord.HTTPException as e:
            logger.error(f"Не удалось переключить роль {self.role_id}: {e}")
            await interaction.response.send_message(
                "Не получилось переключить роль, попробуй ещё раз.", ephemeral=True
            )
