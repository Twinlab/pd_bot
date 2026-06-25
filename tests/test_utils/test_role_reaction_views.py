"""Тесты для persistent-кнопок выдачи ролей (utils/role_reaction_views.py)."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from utils.role_reaction_views import RoleButton, parse_emoji


class TestParseEmoji:
    def test_unicode_emoji_returned_as_is(self):
        assert parse_emoji("👍") == "👍"

    def test_empty_returns_none(self):
        assert parse_emoji("") is None

    def test_custom_emoji_parsed_to_partial(self):
        result = parse_emoji("blob:12345")
        assert isinstance(result, discord.PartialEmoji)
        assert result.name == "blob"
        assert result.id == 12345

    def test_colon_without_id_treated_as_unicode(self):
        assert parse_emoji("a:b") == "a:b"


class TestRoleButton:
    def test_custom_id_encodes_role_id(self):
        button = RoleButton(101, label="Test")
        assert button.item.custom_id == "rr:role:101"
        assert button.role_id == 101

    @pytest.mark.asyncio
    async def test_from_custom_id_restores_role_id(self):
        from utils.role_reaction_views import CUSTOM_ID_TEMPLATE

        match = CUSTOM_ID_TEMPLATE.fullmatch("rr:role:777")
        assert match is not None
        restored = await RoleButton.from_custom_id(MagicMock(), MagicMock(), match)
        assert restored.role_id == 777

    @pytest.mark.asyncio
    async def test_callback_adds_role_when_missing(self):
        role = MagicMock(spec=discord.Role)
        role.id = 101
        role.mention = "<@&101>"
        member = MagicMock(spec=discord.Member)
        member.roles = []
        member.add_roles = AsyncMock()
        member.remove_roles = AsyncMock()
        guild = MagicMock(spec=discord.Guild)
        guild.get_role.return_value = role
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.user = member
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await RoleButton(101).callback(interaction)

        member.add_roles.assert_awaited_once()
        member.remove_roles.assert_not_called()
        assert "Выдал роль" in interaction.response.send_message.await_args.args[0]

    @pytest.mark.asyncio
    async def test_callback_removes_role_when_present(self):
        role = MagicMock(spec=discord.Role)
        role.id = 101
        role.mention = "<@&101>"
        member = MagicMock(spec=discord.Member)
        member.roles = [role]
        member.add_roles = AsyncMock()
        member.remove_roles = AsyncMock()
        guild = MagicMock(spec=discord.Guild)
        guild.get_role.return_value = role
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.user = member
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await RoleButton(101).callback(interaction)

        member.remove_roles.assert_awaited_once()
        member.add_roles.assert_not_called()
        assert "Снял роль" in interaction.response.send_message.await_args.args[0]

    @pytest.mark.asyncio
    async def test_callback_role_missing(self):
        guild = MagicMock(spec=discord.Guild)
        guild.get_role.return_value = None
        member = MagicMock(spec=discord.Member)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.user = member
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await RoleButton(999).callback(interaction)

        assert "не существует" in interaction.response.send_message.await_args.args[0]

    @pytest.mark.asyncio
    async def test_callback_forbidden(self):
        role = MagicMock(spec=discord.Role)
        role.id = 101
        role.mention = "<@&101>"
        member = MagicMock(spec=discord.Member)
        member.roles = []
        member.add_roles = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))
        guild = MagicMock(spec=discord.Guild)
        guild.get_role.return_value = role
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = guild
        interaction.user = member
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await RoleButton(101).callback(interaction)

        assert "нет прав" in interaction.response.send_message.await_args.args[0]
