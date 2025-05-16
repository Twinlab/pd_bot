from unittest.mock import MagicMock

import discord
import pytest

from cogs.role_reaction import RoleReactionCog


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=discord.ext.commands.Bot)
    return bot


@pytest.fixture
def role_reaction_cog(mock_bot):
    return RoleReactionCog(mock_bot)


def test_role_reaction_cog_init(role_reaction_cog):
    assert isinstance(role_reaction_cog, RoleReactionCog)
    assert hasattr(role_reaction_cog, "bot")


@pytest.mark.asyncio
async def test_role_reaction_cog_registers_commands(role_reaction_cog):
    commands = [cmd.name for cmd in role_reaction_cog.get_commands()]
    assert isinstance(commands, list)
    assert len(commands) > 0
