"""Проверки границы публичной перепубликации сообщений."""

from unittest.mock import MagicMock

import discord
import pytest

from utils.channel_permissions import public_message_channel_ids


def _channel(channel_id: int, **permissions: bool) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.overwrites = {}
    channel.permissions_for.return_value = discord.Permissions(
        **{"view_channel": True, "read_message_history": True, **permissions}
    )
    return channel


def test_only_channels_with_public_history_are_allowed() -> None:
    guild = MagicMock(spec=discord.Guild)
    guild.channels = [
        _channel(10),
        _channel(20, view_channel=False),
        _channel(30, read_message_history=False),
    ]
    guild.threads = []

    assert public_message_channel_ids(guild) == {10}


@pytest.mark.parametrize("permission", ["view_channel", "read_message_history"])
def test_member_or_role_deny_prevents_publication(permission: str) -> None:
    guild = MagicMock(spec=discord.Guild)
    channel = _channel(10)
    channel.overwrites = {object(): discord.PermissionOverwrite(**{permission: False})}
    guild.channels = [channel]
    guild.threads = []

    assert public_message_channel_ids(guild) == set()


def test_private_threads_and_unknown_or_restricted_parents_are_excluded() -> None:
    guild = MagicMock(spec=discord.Guild)
    guild.channels = [_channel(10), _channel(20, view_channel=False)]
    guild.threads = []
    for thread_id, parent_id, private in [
        (11, 10, False),
        (12, 10, True),
        (21, 20, False),
        (31, 30, False),
    ]:
        thread = MagicMock(spec=discord.Thread)
        thread.id = thread_id
        thread.parent_id = parent_id
        thread.is_private.return_value = private
        guild.threads.append(thread)

    assert public_message_channel_ids(guild) == {10, 11}


def test_missing_guild_does_not_allow_any_channel() -> None:
    assert public_message_channel_ids(None) == set()
