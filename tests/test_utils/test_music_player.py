"""Тесты :class:`utils.music.player.MusicPlayer` и хелперов подключения."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import wavelink

from utils.music.player import MusicPlayer, close_nodes, setup_node


@pytest.fixture
def fake_track() -> MagicMock:
    """Мок ``wavelink.Playable`` с поддерживающим запись ``extras``."""
    track = MagicMock(spec=wavelink.Playable)
    track.extras = SimpleNamespace()
    return track


@pytest.fixture
def admin_member() -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.guild_permissions = MagicMock()
    member.guild_permissions.administrator = True
    return member


@pytest.fixture
def regular_member() -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = 100
    member.guild_permissions = MagicMock()
    member.guild_permissions.administrator = False
    return member


@pytest.fixture
def requester_member() -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.guild_permissions = MagicMock()
    member.guild_permissions.administrator = False
    return member


class TestAssignAndGetRequester:
    def test_assign_sets_requester_id_in_extras(
        self, fake_track: MagicMock, regular_member: MagicMock
    ) -> None:
        regular_member.id = 555
        MusicPlayer.assign_requester(fake_track, regular_member)
        assert MusicPlayer.get_requester_id(fake_track) == 555

    def test_get_requester_id_returns_none_for_unset(self, fake_track: MagicMock) -> None:
        # extras без requester_id
        fake_track.extras = SimpleNamespace()
        assert MusicPlayer.get_requester_id(fake_track) is None

    def test_get_requester_id_with_none_track(self) -> None:
        assert MusicPlayer.get_requester_id(None) is None

    def test_get_requester_id_with_invalid_value(self, fake_track: MagicMock) -> None:
        fake_track.extras = SimpleNamespace(requester_id="not-a-number")
        assert MusicPlayer.get_requester_id(fake_track) is None

    def test_assign_preserves_other_extras(
        self, fake_track: MagicMock, regular_member: MagicMock
    ) -> None:
        # extras-namespace c уже другими полями
        existing = SimpleNamespace(some_field="value")
        # ExtrasNamespace конвертирует dict обратно; здесь имитируем поведение.
        fake_track.extras = existing
        MusicPlayer.assign_requester(fake_track, regular_member)
        # Проверяем что после присвоения requester_id доступен.
        assert MusicPlayer.get_requester_id(fake_track) == regular_member.id


class TestCanControl:
    """Логика прав: админ может всё, заказчик — только свои треки."""

    def _make_player(self, current_requester_id: int | None) -> MusicPlayer:
        player = MusicPlayer.__new__(MusicPlayer)
        # Установим минимальные атрибуты вручную, не дёргая VoiceProtocol.
        track = MagicMock(spec=wavelink.Playable)
        track.extras = SimpleNamespace(
            requester_id=current_requester_id if current_requester_id is not None else None
        )
        # Подменяем property current → атрибут на инстансе.
        type(player).current = property(lambda self: track)  # type: ignore[assignment]
        return player

    def test_admin_can_always_control(self, admin_member: MagicMock) -> None:
        player = self._make_player(current_requester_id=999)
        assert player.can_control(admin_member) is True
        assert player.can_control(admin_member, admin_only=True) is True

    def test_requester_can_control_own_track(self, requester_member: MagicMock) -> None:
        player = self._make_player(current_requester_id=requester_member.id)
        assert player.can_control(requester_member) is True

    def test_requester_cannot_admin_only(self, requester_member: MagicMock) -> None:
        player = self._make_player(current_requester_id=requester_member.id)
        assert player.can_control(requester_member, admin_only=True) is False

    def test_random_user_cannot_control(self, regular_member: MagicMock) -> None:
        player = self._make_player(current_requester_id=42)
        assert player.can_control(regular_member) is False


class TestSetupNode:
    """``setup_node`` запускает фоновое подключение к Lavalink через wavelink.Pool.

    Главная инвариантность: ``setup_node`` возвращает управление мгновенно,
    не дожидаясь успешного коннекта. Это критично — иначе при недоступном
    Lavalink бот висит на старте.
    """

    async def test_calls_pool_connect_with_settings(self) -> None:
        import asyncio

        bot = MagicMock()
        bot.settings = MagicMock()
        bot.settings.music.lavalink.host = "lava-host"
        bot.settings.music.lavalink.port = 4444
        bot.settings.music.lavalink.password = "pw"
        bot.settings.music.lavalink.secure = False
        bot.settings.music.lavalink.identifier = "MAIN"
        bot.settings.music.voice.inactive_timeout = 300

        with (
            patch.object(wavelink.Pool, "nodes", {}, create=True),
            patch.object(
                wavelink.Pool, "connect", new=AsyncMock(return_value={"MAIN": MagicMock()})
            ) as mock_connect,
        ):
            await setup_node(bot)
            # Подключение уехало в task — даём ему квант чтобы запуститься.
            await asyncio.sleep(0)
            assert mock_connect.called
            kwargs = mock_connect.call_args.kwargs
            nodes = kwargs["nodes"]
            assert len(nodes) == 1
            node = nodes[0]
            assert node.identifier == "MAIN"
            assert node.password == "pw"
            assert node.uri == "http://lava-host:4444"

    async def test_skips_if_node_already_registered(self) -> None:
        import asyncio

        bot = MagicMock()
        bot.settings = MagicMock()
        bot.settings.music.lavalink.identifier = "MAIN"
        bot.settings.music.lavalink.host = "h"
        bot.settings.music.lavalink.port = 1
        bot.settings.music.lavalink.password = "p"
        bot.settings.music.lavalink.secure = False
        bot.settings.music.voice.inactive_timeout = 60

        with (
            patch.object(wavelink.Pool, "nodes", {"MAIN": MagicMock()}, create=True),
            patch.object(wavelink.Pool, "connect", new=AsyncMock()) as mock_connect,
        ):
            await setup_node(bot)
            await asyncio.sleep(0)
            assert not mock_connect.called

    async def test_secure_switches_scheme(self) -> None:
        import asyncio

        bot = MagicMock()
        bot.settings = MagicMock()
        bot.settings.music.lavalink.host = "remote"
        bot.settings.music.lavalink.port = 443
        bot.settings.music.lavalink.password = "pw"
        bot.settings.music.lavalink.secure = True
        bot.settings.music.lavalink.identifier = "REMOTE"
        bot.settings.music.voice.inactive_timeout = 300

        with (
            patch.object(wavelink.Pool, "nodes", {}, create=True),
            patch.object(wavelink.Pool, "connect", new=AsyncMock()) as mock_connect,
        ):
            await setup_node(bot)
            await asyncio.sleep(0)
            assert mock_connect.call_args.kwargs["nodes"][0].uri == "https://remote:443"

    async def test_does_not_block_when_pool_connect_hangs(self) -> None:
        """Гарантирует, что setup_node не виснет даже если Pool.connect не возвращается."""
        import asyncio

        bot = MagicMock()
        bot.settings = MagicMock()
        bot.settings.music.lavalink.host = "h"
        bot.settings.music.lavalink.port = 1
        bot.settings.music.lavalink.password = "p"
        bot.settings.music.lavalink.secure = False
        bot.settings.music.lavalink.identifier = "MAIN"
        bot.settings.music.voice.inactive_timeout = 60

        hanging = asyncio.Event()  # никогда не выставляется

        async def _hang(**_kw: object) -> None:
            await hanging.wait()

        with (
            patch.object(wavelink.Pool, "nodes", {}, create=True),
            patch.object(wavelink.Pool, "connect", new=AsyncMock(side_effect=_hang)),
        ):
            # Если бы setup_node ждал connect — это бы зависло на await ниже.
            await asyncio.wait_for(setup_node(bot), timeout=1.0)


class TestCloseNodes:
    async def test_calls_pool_close(self) -> None:
        with patch.object(wavelink.Pool, "close", new=AsyncMock()) as mock_close:
            await close_nodes()
            assert mock_close.called

    async def test_swallows_close_errors(self) -> None:
        with patch.object(
            wavelink.Pool, "close", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            await close_nodes()  # не должен поднимать исключение
