"""Тесты для utils.penis_utils."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from config.settings import PenisLengthBucket
from utils.penis_utils import _build_description, _color_for_length, _pick_length, measure_penis


def _settings_mock(
    *,
    nuance_chance: float = 0.0,
    not_found_user_ids: list[int] | None = None,
    nuance_text: str = "...но есть нюанс, это у тебя в жопе",
    not_found_text: str = "ошибка, пенис не найден",
    length: int = 5,
) -> MagicMock:
    """Собирает settings с подмодулем fun.penis для тестов.

    По умолчанию используется одна корзина с фиксированной длиной, чтобы выдача
    оставалась детерминированной.
    """
    s = MagicMock()
    s.fun.penis.length_buckets = [
        PenisLengthBucket(min_length=length, max_length=length, weight=1.0)
    ]
    s.fun.penis.nuance_chance = nuance_chance
    s.fun.penis.nuance_text = nuance_text
    s.fun.penis.not_found_user_ids = not_found_user_ids or []
    s.fun.penis.not_found_text = not_found_text
    return s


def _make_ctx(author_id: int = 1) -> MagicMock:
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = author_id
    ctx.author.mention = f"<@{author_id}>"
    return ctx


def _make_user(user_id: int) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.mention = f"<@{user_id}>"
    return user


class TestColorForLength:
    """Цвет эмбеда по длине."""

    def test_green_for_15_plus(self):
        assert _color_for_length(15) == discord.Color.green()
        assert _color_for_length(25) == discord.Color.green()

    def test_gold_for_10_to_14(self):
        assert _color_for_length(10) == discord.Color.gold()
        assert _color_for_length(14) == discord.Color.gold()

    def test_red_for_less_than_10(self):
        assert _color_for_length(0) == discord.Color.red()
        assert _color_for_length(9) == discord.Color.red()


class TestPickLength:
    """Взвешенный выбор длины по корзинам."""

    def test_passes_weights_to_random_choices(self):
        buckets = [
            PenisLengthBucket(min_length=0, max_length=9, weight=37.5),
            PenisLengthBucket(min_length=25, max_length=30, weight=5.0),
        ]
        with (
            patch("utils.penis_utils.random.choices", return_value=[buckets[1]]) as choices_mock,
            patch("utils.penis_utils.random.randint", return_value=27) as randint_mock,
        ):
            result = _pick_length(buckets)

        assert result == 27
        assert choices_mock.call_args.kwargs["weights"] == [37.5, 5.0]
        randint_mock.assert_called_once_with(25, 30)

    def test_result_within_selected_bucket_bounds(self):
        buckets = [PenisLengthBucket(min_length=20, max_length=24, weight=20.0)]
        for _ in range(100):
            length = _pick_length(buckets)
            assert 20 <= length <= 24


class TestBuildDescription:
    """Сборка описания эмбеда."""

    def test_self_without_nuance(self):
        user = _make_user(42)
        desc = _build_description(user=user, is_self=True, representation="8=D", nuance_text=None)
        assert desc == "<@42>, твой пенис\n8=D"

    def test_other_without_nuance(self):
        user = _make_user(42)
        desc = _build_description(user=user, is_self=False, representation="8=D", nuance_text=None)
        assert desc == "Пенис <@42>\n8=D"

    def test_self_with_nuance_appended_on_new_line(self):
        user = _make_user(42)
        desc = _build_description(
            user=user, is_self=True, representation="8=D", nuance_text="нюанс"
        )
        assert desc == "<@42>, твой пенис\n8=D\nнюанс"

    def test_other_with_nuance_appended_on_new_line(self):
        user = _make_user(42)
        desc = _build_description(
            user=user, is_self=False, representation="8=D", nuance_text="нюанс"
        )
        assert desc == "Пенис <@42>\n8=D\nнюанс"

    def test_empty_nuance_string_treated_as_no_nuance(self):
        user = _make_user(42)
        desc = _build_description(user=user, is_self=True, representation="8=D", nuance_text="")
        assert desc == "<@42>, твой пенис\n8=D"


class TestMeasurePenisNotFound:
    """Поведение для пользователей из not_found_user_ids."""

    @pytest.mark.asyncio
    async def test_target_in_not_found_list(self):
        ctx = _make_ctx(author_id=1)
        target = _make_user(user_id=999)
        settings = _settings_mock(not_found_user_ids=[999, 888])
        with patch("config.settings.get_settings", return_value=settings):
            await measure_penis(ctx, target)
        ctx.send.assert_awaited_once_with("ошибка, пенис не найден")

    @pytest.mark.asyncio
    async def test_self_in_not_found_list(self):
        ctx = _make_ctx(author_id=999)
        settings = _settings_mock(not_found_user_ids=[999])
        with patch("config.settings.get_settings", return_value=settings):
            await measure_penis(ctx, None)
        ctx.send.assert_awaited_once_with("ошибка, пенис не найден")

    @pytest.mark.asyncio
    async def test_uses_configured_not_found_text(self):
        ctx = _make_ctx(author_id=1)
        target = _make_user(user_id=42)
        settings = _settings_mock(not_found_user_ids=[42], not_found_text="кастомное сообщение")
        with patch("config.settings.get_settings", return_value=settings):
            await measure_penis(ctx, target)
        ctx.send.assert_awaited_once_with("кастомное сообщение")


class TestMeasurePenisNormal:
    """Обычное поведение измерения с эмбедом."""

    @pytest.mark.asyncio
    async def test_self_measurement_sends_embed(self):
        ctx = _make_ctx(author_id=1)
        settings = _settings_mock()
        with patch("config.settings.get_settings", return_value=settings):
            await measure_penis(ctx, None)

        ctx.send.assert_awaited_once()
        embed = ctx.send.await_args.kwargs["embed"]
        assert isinstance(embed, discord.Embed)
        assert embed.title == "Измеритель пениса"
        assert "твой пенис" in embed.description
        assert "8=====D" in embed.description  # min=max=5

    @pytest.mark.asyncio
    async def test_other_measurement_sends_embed_with_target(self):
        ctx = _make_ctx(author_id=1)
        target = _make_user(user_id=2)
        settings = _settings_mock()
        with patch("config.settings.get_settings", return_value=settings):
            await measure_penis(ctx, target)

        embed = ctx.send.await_args.kwargs["embed"]
        assert "Пенис <@2>" in embed.description

    @pytest.mark.asyncio
    async def test_length_field_present(self):
        ctx = _make_ctx(author_id=1)
        settings = _settings_mock(length=7)
        with patch("config.settings.get_settings", return_value=settings):
            await measure_penis(ctx, None)
        embed = ctx.send.await_args.kwargs["embed"]
        assert any(f.name == "Длина" and f.value == "7 см" for f in embed.fields)


class TestMeasurePenisNuance:
    """Шанс на дописывание nuance_text."""

    @pytest.mark.asyncio
    async def test_no_nuance_when_random_above_chance(self):
        ctx = _make_ctx(author_id=1)
        settings = _settings_mock(nuance_chance=0.10)
        with (
            patch("config.settings.get_settings", return_value=settings),
            patch("utils.penis_utils.random.random", return_value=0.5),  # > 0.10
        ):
            await measure_penis(ctx, None)
        embed = ctx.send.await_args.kwargs["embed"]
        assert "нюанс" not in embed.description

    @pytest.mark.asyncio
    async def test_nuance_appended_when_random_below_chance(self):
        ctx = _make_ctx(author_id=1)
        settings = _settings_mock(nuance_chance=0.10, nuance_text="это у тебя в жопе")
        with (
            patch("config.settings.get_settings", return_value=settings),
            patch("utils.penis_utils.random.random", return_value=0.05),  # < 0.10
        ):
            await measure_penis(ctx, None)
        embed = ctx.send.await_args.kwargs["embed"]
        assert embed.description.endswith("\nэто у тебя в жопе")

    @pytest.mark.asyncio
    async def test_nuance_chance_zero_never_triggers(self):
        ctx = _make_ctx(author_id=1)
        settings = _settings_mock(nuance_chance=0.0, nuance_text="нюанс")
        with (
            patch("config.settings.get_settings", return_value=settings),
            patch("utils.penis_utils.random.random", return_value=0.0),  # >= 0.0 → не сработает
        ):
            await measure_penis(ctx, None)
        embed = ctx.send.await_args.kwargs["embed"]
        assert "нюанс" not in embed.description

    @pytest.mark.asyncio
    async def test_not_found_takes_priority_over_nuance(self):
        ctx = _make_ctx(author_id=42)
        settings = _settings_mock(
            nuance_chance=1.0, not_found_user_ids=[42], not_found_text="не найден"
        )
        with patch("config.settings.get_settings", return_value=settings):
            await measure_penis(ctx, None)
        ctx.send.assert_awaited_once_with("не найден")
