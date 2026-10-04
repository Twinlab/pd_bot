"""Тесты :class:`cogs.music.MusicCog`.

Фокусируемся на чистых утилитах (``_parse_seek``), правах доступа
(``_require_same_voice``) и базовых проверках команд. Глубокая интеграция с
wavelink не покрывается — это уже e2e и требует реального Lavalink.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import wavelink
from discord.ext import commands

from cogs.music import MusicCog
from utils.music.player import MusicPlayer
from utils.music.ui import NowPlayingView, QueueLayoutView, SearchLayoutView
from utils.ui import colors
from utils.ui.testing import joined_text


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
    player.now_playing_view = None
    player.now_playing_lock = asyncio.Lock()
    player._guild = None
    player._volume = 50

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
    requester.voice.channel = mock_player.channel
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


@pytest.mark.parametrize(
    ("query", "identifier"),
    [
        ("Rick Astley Never Gonna Give You Up", "ytsearch:Rick Astley Never Gonna Give You Up"),
        ("Artist: Song", "ytsearch:Artist: Song"),
        ("  scsearch:queen bohemian  ", "scsearch:queen bohemian"),
        ("ytsearch:queen bohemian", "ytsearch:queen bohemian"),
        ("ytmsearch:queen bohemian", "ytmsearch:queen bohemian"),
        ("spsearch:queen bohemian", "spsearch:queen bohemian"),
        (
            "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
    ],
)
async def test_play_routes_search_without_duplicate_prefix(
    cog: MusicCog, mock_player: MusicPlayer, query: str, identifier: str
) -> None:
    """Проверяет запрос к Lavalink через настоящий преобразователь Wavelink."""
    ctx = MagicMock(spec=commands.Context)
    ctx.defer = AsyncMock()
    with (
        patch.object(cog, "_ensure_player", new=AsyncMock(return_value=mock_player)),
        patch("wavelink.Pool.fetch_tracks", new=AsyncMock(return_value=[])) as fetch,
        patch("cogs.music.safe_send_error", new=AsyncMock()),
    ):
        await MusicCog.play.callback(cog, ctx, query=query)

    fetch.assert_awaited_once_with(identifier, node=None)


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

    @pytest.mark.parametrize("can_control", [False, True])
    async def test_resume_checks_requester_or_admin(
        self, cog: MusicCog, mock_player: MusicPlayer, monkeypatch, can_control: bool
    ) -> None:
        ctx = MagicMock(spec=commands.Context)
        ctx.author = MagicMock(spec=discord.Member)
        monkeypatch.setattr(type(mock_player), "paused", property(lambda self: True))
        with (
            patch.object(cog, "_require_same_voice", return_value=mock_player),
            patch.object(mock_player, "can_control", return_value=can_control) as check,
            patch.object(mock_player, "pause", new=AsyncMock()) as pause,
            patch.object(cog, "_send_status", new=AsyncMock()),
            patch("cogs.music.safe_send_error", new=AsyncMock()) as send_error,
        ):
            await self._raw_callback(cog.resume)(cog, ctx)

        check.assert_called_once_with(ctx.author)
        if can_control:
            pause.assert_awaited_once_with(False)
            send_error.assert_not_awaited()
        else:
            pause.assert_not_awaited()
            send_error.assert_awaited_once()

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
        self, cog: MusicCog, mock_player: MusicPlayer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Сделаем плеер играющим, но с невалидным значением position
        track = SimpleNamespace(length=120_000)
        monkeypatch.setattr(type(mock_player), "current", property(lambda self: track))
        monkeypatch.setattr(type(mock_player), "playing", property(lambda self: True))

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


def _track(title: str = "Song") -> MagicMock:
    track = MagicMock(spec=wavelink.Playable)
    track.title = title
    track.author = "Band"
    track.uri = "https://example.com/song"
    track.artwork = None
    track.source = "youtube"
    track.length = 120_000
    track.extras = SimpleNamespace(requester_id=None)
    return track


class TestCanonicalMusicPanel:
    def _context(self, player: MusicPlayer) -> MagicMock:
        ctx = MagicMock(spec=commands.Context)
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.voice.channel = player.channel
        ctx.author.guild_permissions.administrator = True
        ctx.guild.voice_client = player
        ctx.send = AsyncMock()
        ctx.defer = AsyncMock()
        return ctx

    @pytest.mark.parametrize(
        ("command", "kwargs"),
        [
            ("pause", {}),
            ("resume", {}),
            ("loop", {"mode": "queue"}),
            ("shuffle", {}),
            ("clearqueue", {}),
            ("remove", {"index": 1}),
            ("volume", {"value": 75}),
            ("seek", {"position": "0:30"}),
        ],
    )
    async def test_slash_mutations_refresh_existing_panel(
        self, cog, mock_player, monkeypatch, command, kwargs
    ) -> None:
        track = _track()
        monkeypatch.setattr(type(mock_player), "current", property(lambda self: track))
        monkeypatch.setattr(type(mock_player), "playing", property(lambda self: True))
        state = {"paused": command == "resume"}
        monkeypatch.setattr(type(mock_player), "paused", property(lambda self: state["paused"]))
        mock_player.queue = wavelink.Queue()
        mock_player.queue.put([_track("Next"), _track("Last")])
        mock_player.text_channel = MagicMock(spec=discord.TextChannel)
        mock_player.text_channel.send = AsyncMock()
        mock_player.now_playing_message = MagicMock(spec=discord.Message)
        mock_player.now_playing_message.edit = AsyncMock()
        mock_player.now_playing_view = NowPlayingView(mock_player)

        async def pause(value):
            state["paused"] = value

        mock_player.pause = AsyncMock(side_effect=pause)
        mock_player.set_volume = AsyncMock()
        mock_player.seek = AsyncMock()
        ctx = self._context(mock_player)
        callback = getattr(cog, command).callback.__wrapped__
        await callback(cog, ctx, **kwargs)

        ctx.defer.assert_awaited_once()
        mock_player.now_playing_message.edit.assert_awaited_once()
        mock_player.text_channel.send.assert_not_awaited()
        panel = mock_player.now_playing_message.edit.call_args.kwargs["view"]
        if command in {"pause", "resume"}:
            assert ("⏸️" if command == "pause" else "▶️") in joined_text(panel)
        if command == "clearqueue":
            assert "Следующий" not in joined_text(panel)
        if command == "remove":
            assert "Last" in joined_text(panel)
            assert "Next" not in joined_text(panel)
        if command == "loop":
            assert any(
                isinstance(item, discord.ui.Button) and item.label == "Повтор: очередь"
                for item in panel.walk_children()
            )

    async def test_nowplaying_reopens_same_panel_without_public_duplicate(
        self, cog, mock_player, monkeypatch
    ) -> None:
        monkeypatch.setattr(type(mock_player), "current", property(lambda self: _track()))
        mock_player.text_channel = MagicMock(spec=discord.TextChannel)
        mock_player.text_channel.send = AsyncMock()
        message = MagicMock(spec=discord.Message)
        message.edit = AsyncMock()
        message.jump_url = "https://discord.com/channels/1/2/3"
        mock_player.now_playing_message = message
        mock_player.now_playing_view = NowPlayingView(mock_player)
        mock_player.now_playing_view.stop()
        ctx = self._context(mock_player)

        await cog.nowplaying.callback.__wrapped__(cog, ctx)
        view = mock_player.now_playing_view
        await cog.nowplaying.callback.__wrapped__(cog, ctx)

        assert mock_player.now_playing_view is view
        assert not view.is_finished()
        assert message.edit.await_count == 2
        mock_player.text_channel.send.assert_not_awaited()
        assert all(call.kwargs == {"ephemeral": True} for call in ctx.send.call_args_list)
        assert all(message.jump_url in call.args[0] for call in ctx.send.call_args_list)

    async def test_nowplaying_reports_failed_edit_instead_of_success_link(
        self, cog, mock_player, monkeypatch
    ) -> None:
        monkeypatch.setattr(type(mock_player), "current", property(lambda self: _track()))
        mock_player.now_playing_message = MagicMock(spec=discord.Message)
        mock_player.now_playing_message.edit = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(status=500), "unavailable")
        )
        ctx = self._context(mock_player)
        with patch("cogs.music.safe_send_error", new=AsyncMock()) as error:
            await cog.nowplaying.callback.__wrapped__(cog, ctx)
        error.assert_awaited_once()
        ctx.send.assert_not_awaited()

    async def test_nowplaying_checks_actual_message_channel(self, cog, mock_player, monkeypatch):
        monkeypatch.setattr(type(mock_player), "current", property(lambda self: _track()))
        mock_player.now_playing_message = MagicMock(spec=discord.Message)
        original_channel = MagicMock(spec=discord.TextChannel)
        original_channel.permissions_for.return_value.view_channel = False
        mock_player.now_playing_message.channel = original_channel
        mock_player.text_channel = MagicMock(spec=discord.TextChannel)
        mock_player.text_channel.permissions_for.return_value.view_channel = True
        ctx = self._context(mock_player)
        with (
            patch("cogs.music.safe_send_error", new=AsyncMock()) as error,
            patch.object(cog, "_publish_now_playing", new=AsyncMock()) as refresh,
        ):
            await cog.nowplaying.callback.__wrapped__(cog, ctx)
        error.assert_awaited_once()
        refresh.assert_not_awaited()

    async def test_slash_stop_closes_canonical_panel(self, cog, mock_player) -> None:
        mock_player.now_playing_message = MagicMock(spec=discord.Message)
        mock_player.now_playing_message.edit = AsyncMock()
        view = NowPlayingView(mock_player)
        mock_player.now_playing_view = view
        mock_player.disconnect = AsyncMock()
        await cog.stop.callback.__wrapped__(cog, self._context(mock_player))
        assert view.is_finished()
        assert mock_player.now_playing_view is None
        card = mock_player.now_playing_message.edit.call_args.kwargs["view"]
        assert "остановлено" in joined_text(card)

    @pytest.mark.parametrize("command", ["stop", "clearqueue", "volume"])
    def test_admin_metadata_matches_runtime_restrictions(self, cog, command):
        assert getattr(cog, command).app_command.default_permissions.administrator

    async def test_queue_command_binds_sent_message(self, cog, mock_player, monkeypatch):
        monkeypatch.setattr(type(mock_player), "current", property(lambda self: _track()))
        ctx = self._context(mock_player)
        await cog.queue.callback.__wrapped__(cog, ctx)
        view = ctx.send.call_args.kwargs["view"]
        assert isinstance(view, QueueLayoutView)
        assert view.message is ctx.send.return_value

    async def test_search_command_binds_sent_message(self, cog, mock_player):
        ctx = self._context(mock_player)
        with (
            patch.object(cog, "_ensure_player", new=AsyncMock(return_value=mock_player)),
            patch("wavelink.Playable.search", new=AsyncMock(return_value=[_track(), _track("Two")])),
        ):
            await cog.play.callback.__wrapped__(cog, ctx, query="Song")
        view = ctx.send.call_args.kwargs["view"]
        assert isinstance(view, SearchLayoutView)
        assert view.message is ctx.send.return_value

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
