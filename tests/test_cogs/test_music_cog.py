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
from utils.ui import colors


@pytest.fixture
def cog() -> MusicCog:
    """Голый ког с моком бота."""
    bot = MagicMock(spec=commands.Bot)
    return MusicCog(bot)


@pytest.fixture
def mock_player(monkeypatch: pytest.MonkeyPatch) -> MusicPlayer:
    """Минимальный MusicPlayer для проверок."""
    player = MusicPlayer.__new__(MusicPlayer)
    player.text_channel = None
    player.now_playing_message = None

    monkeypatch.setattr(type(player), "current", property(lambda self: None))
    monkeypatch.setattr(type(player), "playing", property(lambda self: False))
    monkeypatch.setattr(type(player), "paused", property(lambda self: False))
    monkeypatch.setattr(type(player), "connected", property(lambda self: True))

    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = "Voice"
    monkeypatch.setattr(type(player), "channel", property(lambda self, _c=channel: _c), raising=False)

    queue = MagicMock(spec=wavelink.Queue)
    queue.__len__ = lambda self: 0
    queue.is_empty = True
    queue.mode = wavelink.QueueMode.normal
    player.queue = queue
    return player


async def test_track_selection_acknowledges_before_enqueue(
    cog: MusicCog, mock_player: MusicPlayer
) -> None:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild.voice_client = mock_player
    interaction.response.defer = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    requester = MagicMock(spec=discord.Member)
    track = MagicMock(spec=wavelink.Playable)
    card = discord.ui.LayoutView()

    async def enqueue(*args, **kwargs) -> int:
        interaction.response.defer.assert_awaited_once()
        interaction.edit_original_response.assert_not_awaited()
        return 3

    with (
        patch.object(cog, "_enqueue", new=AsyncMock(side_effect=enqueue)) as enqueue_mock,
        patch("cogs.music.added_to_queue_card", return_value=card) as build_card,
    ):
        await cog._enqueue_selected_track(interaction, track, requester)

    enqueue_mock.assert_awaited_once_with(mock_player, track, requester)
    build_card.assert_called_once_with(track, 3, mock_player)
    interaction.edit_original_response.assert_awaited_once_with(view=card)
    interaction.response.edit_message.assert_not_awaited()


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


class TestEnsurePlayer:
    async def test_voice_timeout_cleans_registered_client(self, cog: MusicCog) -> None:
        ctx = MagicMock(spec=commands.Context)
        guild = MagicMock(spec=discord.Guild)
        guild.voice_client = None
        ctx.guild = guild

        channel = MagicMock(spec=discord.VoiceChannel)
        failed_player = MagicMock(spec=MusicPlayer)
        failed_player.disconnect = AsyncMock()

        async def fail_connect(**_kwargs: object) -> None:
            guild.voice_client = failed_player
            raise wavelink.ChannelTimeoutException("timeout")

        channel.connect = AsyncMock(side_effect=fail_connect)
        member = MagicMock(spec=discord.Member)
        member.voice = MagicMock(spec=discord.VoiceState)
        member.voice.channel = channel
        ctx.author = member

        with patch("cogs.music.safe_send_error", new=AsyncMock()) as mock_error:
            result = await cog._ensure_player(ctx)

        assert result is None
        failed_player.disconnect.assert_awaited_once_with(force=True)
        mock_error.assert_awaited_once()


class TestPresentation:
    """Хелперы отрисовки всегда отправляют карточки Components V2."""

    async def test_send_status_uses_status_card(self, cog: MusicCog) -> None:
        ctx = MagicMock(spec=commands.Context)
        ctx.send = AsyncMock()
        card = discord.ui.LayoutView()
        with patch("cogs.music.status_card", return_value=card) as mock_status_card:
            await cog._send_status(ctx, "⏸️ Пауза", kind="info")

        mock_status_card.assert_called_once_with("⏸️ Пауза", "", colors.INFO)
        ctx.send.assert_awaited_once_with(view=card)

    async def test_send_added_uses_card(self, cog: MusicCog, mock_player: MusicPlayer) -> None:
        ctx = MagicMock(spec=commands.Context)
        ctx.send = AsyncMock()
        track = MagicMock(spec=wavelink.Playable)
        card = discord.ui.LayoutView()
        with patch("cogs.music.added_to_queue_card", return_value=card) as mock_card:
            await cog._send_added(ctx, track, position=1, player=mock_player)

        mock_card.assert_called_once_with(track, 1, mock_player)
        ctx.send.assert_awaited_once_with(view=card)


class TestTrackException:
    async def test_uses_dict_fields_and_truncates_discord_message(self, cog: MusicCog) -> None:
        player = MusicPlayer.__new__(MusicPlayer)
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        player.text_channel = channel

        payload = SimpleNamespace(
            player=player,
            track=SimpleNamespace(title="Broken track"),
            exception={
                "message": "failure " * 1000,
                "severity": "SUSPICIOUS",
                "cause": "FriendlyException",
            },
        )
        card = discord.ui.LayoutView()

        with (
            patch("cogs.music.status_card", return_value=card) as mock_status_card,
            patch("cogs.music.logger.error") as mock_log,
        ):
            await cog.on_wavelink_track_exception(payload)

        log_args = mock_log.call_args.args
        assert log_args[3:] == ("SUSPICIOUS", "FriendlyException")
        assert len(log_args[2]) <= 1500
        title, description, accent = mock_status_card.call_args.args
        assert title == "❌ Ошибка воспроизведения"
        assert "failure" in description
        assert len(description) < 800
        assert accent == colors.ERROR
        channel.send.assert_awaited_once_with(view=card)
