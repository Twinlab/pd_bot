"""Тесты :class:`cogs.music.MusicCog`.

Фокусируемся на чистых утилитах (``_parse_seek``), правах доступа
(``_require_same_voice``) и базовых проверках команд. Глубокая интеграция с
wavelink не покрывается — это уже e2e и требует реального Lavalink.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import wavelink
from discord.ext import commands

from cogs.music import MusicCog
from utils.music.player import MusicPlayer


@pytest.fixture
def cog() -> MusicCog:
    """Голый ког с моком бота."""
    bot = MagicMock(spec=commands.Bot)
    return MusicCog(bot)


@pytest.fixture
def mock_player() -> MusicPlayer:
    """Минимальный MusicPlayer для проверок."""
    player = MusicPlayer.__new__(MusicPlayer)
    player.text_channel = None
    player.now_playing_message = None

    type(player).current = property(lambda self: None)  # type: ignore[assignment]
    type(player).playing = property(lambda self: False)  # type: ignore[assignment]
    type(player).paused = property(lambda self: False)  # type: ignore[assignment]
    type(player).connected = property(lambda self: True)  # type: ignore[assignment]

    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = "Voice"
    type(player).channel = property(lambda self, _c=channel: _c)  # type: ignore[assignment]

    queue = MagicMock(spec=wavelink.Queue)
    queue.__len__ = lambda self: 0
    queue.is_empty = True
    queue.mode = wavelink.QueueMode.normal
    player.queue = queue
    return player


class TestParseSeek:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("0", 0),
            ("90", 90),
            ("1:23", 83),
            ("01:23", 83),
            ("00:30", 30),
            ("1:02:03", 3723),
            ("0:00:01", 1),
        ],
    )
    def test_valid_inputs(self, value: str, expected: int) -> None:
        assert MusicCog._parse_seek(value) == expected

    @pytest.mark.parametrize(
        "value",
        ["", "abc", "1:60", "1:23:60", "1:2:3:4", "-5"],
    )
    def test_invalid_inputs_return_none(self, value: str) -> None:
        assert MusicCog._parse_seek(value) is None


class TestRequireSameVoice:
    def _make_ctx(
        self,
        *,
        in_voice: bool = True,
        voice_channel: object | None = None,
        guild_voice_client: object | None = None,
    ) -> MagicMock:
        ctx = MagicMock(spec=commands.Context)
        guild = MagicMock(spec=discord.Guild)
        guild.voice_client = guild_voice_client
        ctx.guild = guild
        member = MagicMock(spec=discord.Member)
        if in_voice:
            member.voice = MagicMock(spec=discord.VoiceState)
            member.voice.channel = voice_channel
        else:
            member.voice = None
        ctx.author = member
        return ctx

    def test_returns_none_when_no_voice_client(self, cog: MusicCog) -> None:
        ctx = self._make_ctx(guild_voice_client=None)
        assert cog._require_same_voice(ctx) is None

    def test_returns_none_when_user_not_in_voice(
        self, cog: MusicCog, mock_player: MusicPlayer
    ) -> None:
        ctx = self._make_ctx(in_voice=False, guild_voice_client=mock_player)
        assert cog._require_same_voice(ctx) is None

    def test_returns_none_when_different_channel(
        self, cog: MusicCog, mock_player: MusicPlayer
    ) -> None:
        other_channel = MagicMock(spec=discord.VoiceChannel)
        ctx = self._make_ctx(voice_channel=other_channel, guild_voice_client=mock_player)
        assert cog._require_same_voice(ctx) is None

    def test_returns_player_when_same_channel(
        self, cog: MusicCog, mock_player: MusicPlayer
    ) -> None:
        # Канал у player и user — один и тот же
        same_channel = mock_player.channel
        ctx = self._make_ctx(voice_channel=same_channel, guild_voice_client=mock_player)
        assert cog._require_same_voice(ctx) is mock_player


class TestCommandsGuardErrors:
    """Команды без подходящего плеера должны вежливо отказывать."""

    @staticmethod
    def _raw_callback(hybrid_cmd: commands.HybridCommand) -> object:
        """Возвращает исходную функцию команды (минуя ``@command_error_handler``).

        ``commands.hybrid_command`` хранит wrapped-функцию в ``.callback``;
        ``command_error_handler`` использует ``functools.wraps`` и кладёт
        исходную функцию в ``__wrapped__``.
        """
        wrapped = hybrid_cmd.callback
        return getattr(wrapped, "__wrapped__", wrapped)

    async def test_skip_without_player_sends_error(self, cog: MusicCog) -> None:
        ctx = MagicMock(spec=commands.Context)
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.voice_client = None
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.voice = None

        with patch("cogs.music.safe_send_error", new=AsyncMock()) as mock_err:
            await self._raw_callback(cog.skip)(cog, ctx)
            mock_err.assert_called_once()

    async def test_nowplaying_without_player_sends_error(self, cog: MusicCog) -> None:
        ctx = MagicMock(spec=commands.Context)
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.voice_client = None

        with patch("cogs.music.safe_send_error", new=AsyncMock()) as mock_err:
            await self._raw_callback(cog.nowplaying)(cog, ctx)
            mock_err.assert_called_once()

    async def test_seek_rejects_invalid_position(
        self, cog: MusicCog, mock_player: MusicPlayer
    ) -> None:
        # Сделаем плеер играющим, но с невалидным значением position
        track = SimpleNamespace(length=120_000)
        type(mock_player).current = property(lambda self: track)  # type: ignore[assignment]
        type(mock_player).playing = property(lambda self: True)  # type: ignore[assignment]

        ctx = MagicMock(spec=commands.Context)
        guild = MagicMock(spec=discord.Guild)
        guild.voice_client = mock_player
        ctx.guild = guild
        member = MagicMock(spec=discord.Member)
        member.voice = MagicMock()
        member.voice.channel = mock_player.channel
        member.guild_permissions = MagicMock()
        member.guild_permissions.administrator = True
        ctx.author = member

        with patch("cogs.music.safe_send_error", new=AsyncMock()) as mock_err:
            await self._raw_callback(cog.seek)(cog, ctx, "broken-value")
            mock_err.assert_called_once()
            args, _ = mock_err.call_args
            assert "позицию" in args[1].lower() or "разобрать" in args[1].lower()
