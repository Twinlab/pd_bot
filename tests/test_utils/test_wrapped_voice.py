"""Тесты предиката голосовой активности."""

from unittest.mock import MagicMock

from utils.wrapped.voice import count_humans, is_active_voice_state, member_is_active


class TestIsActiveVoiceState:
    """Тесты чистой функции is_active_voice_state."""

    def _base_kwargs(self, **overrides):
        kwargs = {
            "channel_id": 10,
            "afk_channel_id": 99,
            "self_deaf": False,
            "deaf": False,
            "self_mute": False,
            "mute": False,
            "human_count": 2,
            "count_while_muted": True,
            "min_humans": 2,
        }
        kwargs.update(overrides)
        return kwargs

    def test_active_when_all_good(self):
        assert is_active_voice_state(**self._base_kwargs()) is True

    def test_inactive_when_not_in_voice(self):
        assert is_active_voice_state(**self._base_kwargs(channel_id=None)) is False

    def test_inactive_in_afk_channel(self):
        assert is_active_voice_state(**self._base_kwargs(channel_id=99)) is False

    def test_inactive_when_self_deaf(self):
        assert is_active_voice_state(**self._base_kwargs(self_deaf=True)) is False

    def test_inactive_when_server_deaf(self):
        assert is_active_voice_state(**self._base_kwargs(deaf=True)) is False

    def test_inactive_when_alone(self):
        assert is_active_voice_state(**self._base_kwargs(human_count=1)) is False

    def test_muted_counts_by_default(self):
        assert is_active_voice_state(**self._base_kwargs(self_mute=True)) is True

    def test_muted_not_counted_when_disabled(self):
        assert (
            is_active_voice_state(**self._base_kwargs(self_mute=True, count_while_muted=False))
            is False
        )

    def test_no_afk_channel_configured(self):
        assert is_active_voice_state(**self._base_kwargs(afk_channel_id=None)) is True


class TestCountHumans:
    """Тесты подсчёта живых участников канала."""

    def test_none_channel(self):
        assert count_humans(None) == 0

    def test_excludes_bots(self):
        human = MagicMock()
        human.bot = False
        bot = MagicMock()
        bot.bot = True
        channel = MagicMock()
        channel.members = [human, bot, human]
        assert count_humans(channel) == 2


class TestMemberIsActive:
    """Тесты обёртки member_is_active."""

    def _member(self, *, channel_id=10, afk_id=99, self_deaf=False, members=None):
        channel = MagicMock()
        channel.id = channel_id
        channel.members = members if members is not None else [MagicMock(bot=False)] * 2

        afk = MagicMock()
        afk.id = afk_id

        member = MagicMock()
        member.voice = MagicMock()
        member.voice.channel = channel
        member.voice.self_deaf = self_deaf
        member.voice.deaf = False
        member.voice.self_mute = False
        member.voice.mute = False
        member.guild = MagicMock()
        member.guild.afk_channel = afk
        return member

    def test_active(self):
        member = self._member()
        assert member_is_active(member, count_while_muted=True, min_humans=2) is True

    def test_not_in_voice(self):
        member = MagicMock()
        member.voice = None
        assert member_is_active(member, count_while_muted=True, min_humans=2) is False

    def test_alone_inactive(self):
        member = self._member(members=[MagicMock(bot=False)])
        assert member_is_active(member, count_while_muted=True, min_humans=2) is False

    def test_deaf_inactive(self):
        member = self._member(self_deaf=True)
        assert member_is_active(member, count_while_muted=True, min_humans=2) is False
