"""Тесты для TopReactionsCog — листенеры реакций и команда /topreactions."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.top_reactions import (
    TopReactionsCog,
    TopReactionsView,
    _build_authors_embed,
    _build_embed,
    _format_preview,
    _period_label,
)
from utils.top_reactions_data_manager import AuthorLeaderboardEntry, LeaderboardEntry


@pytest.fixture
def mock_manager():
    """Полностью замокированный TopReactionsDataManager."""
    m = MagicMock()
    m.upsert_message = AsyncMock()
    m.add_reactor = AsyncMock(return_value=True)
    m.remove_reactor = AsyncMock(return_value=True)
    m.remove_all_reactors_for_message = AsyncMock(return_value=0)
    m.remove_emoji_for_message = AsyncMock(return_value=0)
    m.message_exists = AsyncMock(return_value=False)
    m.mark_deleted = AsyncMock()
    m.get_leaderboard = AsyncMock(return_value=[])
    return m


@pytest.fixture
def cog(mock_bot, mock_manager):
    """Экземпляр кога с замоканным менеджером."""
    with patch("cogs.top_reactions.TopReactionsDataManager", return_value=mock_manager):
        c = TopReactionsCog(mock_bot)
    c.manager = mock_manager
    return c


def _make_payload(*, user_id: int, message_id: int, channel_id: int, emoji: str = "👍"):
    """Создаёт мок RawReactionActionEvent."""
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.user_id = user_id
    payload.message_id = message_id
    payload.channel_id = channel_id
    payload.emoji = MagicMock()
    payload.emoji.__str__ = lambda self: emoji
    return payload


class TestCogInit:
    def test_cog_initializes(self, mock_bot):
        with patch("cogs.top_reactions.TopReactionsDataManager"):
            c = TopReactionsCog(mock_bot)
        assert c.bot == mock_bot
        assert c.cog_name == "TopReactions"

    def test_cog_registers_command(self, cog):
        names = [cmd.name for cmd in cog.get_commands()]
        assert "topreactions" in names
        assert "topauthors" in names


class TestReactionAdd:
    @pytest.mark.asyncio
    async def test_ignores_bot_reactions(self, cog, mock_bot):
        bot_id = mock_bot.user.id
        payload = _make_payload(user_id=bot_id, message_id=1, channel_id=2)
        await cog.on_raw_reaction_add(payload)
        cog.manager.add_reactor.assert_not_called()
        cog.manager.message_exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_known_message_just_adds_reactor(self, cog):
        cog.manager.message_exists.return_value = True
        payload = _make_payload(user_id=42, message_id=100, channel_id=200, emoji="🔥")
        await cog.on_raw_reaction_add(payload)
        cog.manager.add_reactor.assert_called_once_with(message_id=100, user_id=42, emoji="🔥")

    @pytest.mark.asyncio
    async def test_unknown_message_triggers_backfill(self, cog, mock_bot):
        """При реакции на незнакомое сообщение должен сработать fetch + backfill."""
        cog.manager.message_exists.return_value = False

        # Готовим fake-канал с fetch_message
        fake_message = MagicMock(spec=discord.Message)
        fake_message.id = 100
        fake_message.channel = MagicMock()
        fake_message.channel.id = 200
        fake_message.author = MagicMock()
        fake_message.author.id = 42
        fake_message.content = "test"
        fake_message.jump_url = "https://discord.com/x/100"
        fake_message.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        fake_message.reactions = []  # пустой список реакций

        fake_channel = MagicMock(spec=discord.TextChannel)
        fake_channel.fetch_message = AsyncMock(return_value=fake_message)
        mock_bot.get_channel = MagicMock(return_value=fake_channel)

        payload = _make_payload(user_id=42, message_id=100, channel_id=200)
        await cog.on_raw_reaction_add(payload)

        cog.manager.upsert_message.assert_called_once()
        # add_reactor НЕ должен быть вызван напрямую (backfill сам всё делает)
        cog.manager.add_reactor.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_message_not_found(self, cog, mock_bot):
        """Если fetch_message бросает NotFound — игнорируем."""
        cog.manager.message_exists.return_value = False

        fake_channel = MagicMock(spec=discord.TextChannel)
        fake_channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "x"))
        mock_bot.get_channel = MagicMock(return_value=fake_channel)

        payload = _make_payload(user_id=42, message_id=100, channel_id=200)
        # Не должно бросить
        await cog.on_raw_reaction_add(payload)
        cog.manager.upsert_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_channel_not_found(self, cog, mock_bot):
        """Если канал не найден — игнорируем."""
        cog.manager.message_exists.return_value = False
        mock_bot.get_channel = MagicMock(return_value=None)
        mock_bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), "x"))

        payload = _make_payload(user_id=42, message_id=100, channel_id=200)
        await cog.on_raw_reaction_add(payload)
        cog.manager.upsert_message.assert_not_called()


class TestReactionRemove:
    @pytest.mark.asyncio
    async def test_ignores_bot(self, cog, mock_bot):
        payload = _make_payload(user_id=mock_bot.user.id, message_id=1, channel_id=2)
        await cog.on_raw_reaction_remove(payload)
        cog.manager.remove_reactor.assert_not_called()

    @pytest.mark.asyncio
    async def test_removes_specific_reactor(self, cog):
        payload = _make_payload(user_id=42, message_id=100, channel_id=200, emoji="🔥")
        await cog.on_raw_reaction_remove(payload)
        cog.manager.remove_reactor.assert_called_once_with(message_id=100, user_id=42, emoji="🔥")


class TestReactionClear:
    @pytest.mark.asyncio
    async def test_clear_all_reactions(self, cog):
        payload = MagicMock(spec=discord.RawReactionClearEvent)
        payload.message_id = 100
        await cog.on_raw_reaction_clear(payload)
        cog.manager.remove_all_reactors_for_message.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_clear_emoji(self, cog):
        payload = MagicMock(spec=discord.RawReactionClearEmojiEvent)
        payload.message_id = 100
        payload.emoji = MagicMock()
        payload.emoji.__str__ = lambda self: "🔥"
        await cog.on_raw_reaction_clear_emoji(payload)
        cog.manager.remove_emoji_for_message.assert_called_once_with(100, "🔥")


class TestMessageDelete:
    @pytest.mark.asyncio
    async def test_marks_deleted(self, cog):
        payload = MagicMock(spec=discord.RawMessageDeleteEvent)
        payload.message_id = 100
        await cog.on_raw_message_delete(payload)
        cog.manager.mark_deleted.assert_called_once_with(100)


class TestEmbedBuild:
    """Тесты функции _build_embed."""

    def test_empty_entries(self):
        embed = _build_embed(
            entries=[],
            page=0,
            total_pages=1,
            period="month",
            guild=None,
        )
        assert "Пока нет" in embed.description

    def test_with_entries(self):
        entries = [
            LeaderboardEntry(
                message_id=1,
                channel_id=2,
                author_id=3,
                content="Hello world",
                jump_url="https://discord.com/x/1",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reactor_count=15,
                is_historical=False,
            ),
            LeaderboardEntry(
                message_id=2,
                channel_id=2,
                author_id=4,
                content="Архивное",
                jump_url="https://discord.com/x/2",
                posted_at=datetime(2020, 1, 1, tzinfo=UTC),
                reactor_count=42,
                is_historical=True,
            ),
        ]
        embed = _build_embed(
            entries=entries,
            page=0,
            total_pages=1,
            period="all",
            guild=None,
        )
        assert "🥇" in embed.description
        assert "🥈" in embed.description
        assert "15" in embed.description
        assert "42" in embed.description
        assert "архив" in embed.description  # историческое помечено

    def test_pagination_footer(self):
        entries = [
            LeaderboardEntry(
                message_id=1,
                channel_id=2,
                author_id=3,
                content="x",
                jump_url="https://x",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reactor_count=1,
                is_historical=False,
            )
        ]
        embed = _build_embed(entries=entries, page=2, total_pages=5, period="all", guild=None)
        assert embed.footer.text == "Страница 3 из 5"

    def test_rank_prefix_has_no_padding_spaces(self):
        """Регрессия: раньше использовался `:>2` → выводилось `#  4` вместо `#4`."""
        entries = [
            LeaderboardEntry(
                message_id=i,
                channel_id=2,
                author_id=3,
                content="x",
                jump_url=f"https://x/{i}",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reactor_count=10 - i,
                is_historical=False,
            )
            for i in range(1, 6)
        ]
        embed = _build_embed(entries=entries, page=0, total_pages=1, period="all", guild=None)
        # Никаких ` #4` или ` # 4` — ранг должен быть слитный.
        assert "`#4`" in embed.description
        assert "`#5`" in embed.description
        assert "` #" not in embed.description
        assert "`# " not in embed.description

    def test_markdown_links_escaped_but_jump_link_intact(self):
        """Квадратные скобки из текста эскейпятся, а наш jump-link остаётся валидным."""
        nasty = (
            "[Нужна роль? Нажми на реакцию] (link): "
            "разрываем *ладдер* и `ворота` _соперников_ | очень длинное "
            "сообщение которое раньше ломало вёрстку"
        )
        entries = [
            LeaderboardEntry(
                message_id=1,
                channel_id=2,
                author_id=3,
                content=nasty,
                jump_url="https://discord.com/x/1",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reactor_count=31,
                is_historical=False,
            )
        ]
        embed = _build_embed(entries=entries, page=0, total_pages=1, period="all", guild=None)
        assert r"\[" in embed.description
        assert r"\]" in embed.description
        assert "](https://discord.com/x/1)" in embed.description

    def test_mentions_and_custom_emoji_survive(self):
        """Упоминания и кастомные эмодзи не эскейпятся — Discord их отрендерит."""
        content = "пинг <@&1366870323965726900> и эмодзи <:pepe:123456789>"
        entries = [
            LeaderboardEntry(
                message_id=1,
                channel_id=2,
                author_id=3,
                content=content,
                jump_url="https://discord.com/x/1",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reactor_count=5,
                is_historical=False,
            )
        ]
        embed = _build_embed(entries=entries, page=0, total_pages=1, period="all", guild=None)
        assert "<@&1366870323965726900>" in embed.description
        assert "<:pepe:123456789>" in embed.description


class TestFormatPreview:
    """Юнит-тесты для _format_preview."""

    def test_collapses_whitespace(self):
        assert _format_preview("a   b\n\nc\td", 100) == "a b c d"

    def test_empty_returns_placeholder(self):
        assert _format_preview("", 100) == "*(вложение / без текста)*"
        assert _format_preview("   \n\t  ", 100) == "*(вложение / без текста)*"

    def test_truncates_to_max_len_with_ellipsis(self):
        result = _format_preview("a" * 200, max_len=50)
        assert len(result) == 50
        assert result.endswith("…")

    def test_escapes_brackets_but_not_parens(self):
        """Квадратные скобки блокируем (masked-link), круглые оставляем."""
        result = _format_preview("[click](url)", 100)
        assert result == r"\[click\](url)"

    def test_preserves_mentions_emoji_and_formatting(self):
        """Эскейпим только `[ ] \\``; упоминания/эмодзи/`*_~|>` остаются как есть."""
        result = _format_preview("a*b_c~d`e|f>g\\h <@&1> <:pepe:2>", 100)
        assert result == r"a*b_c~d\`e|f>g\\h <@&1> <:pepe:2>"

    def test_short_text_passes_through(self):
        assert _format_preview("hello world", 100) == "hello world"


class TestExcludedMessageIds:
    """Тесты сборки чёрного списка id для get_leaderboard."""

    def _settings_with(
        self,
        *,
        ignored_message_ids: list[int],
        ignore_role_reaction: bool,
    ) -> MagicMock:
        s = MagicMock()
        s.top_reactions.ignored_message_ids = ignored_message_ids
        s.top_reactions.ignore_role_reaction_message = ignore_role_reaction
        return s

    @pytest.mark.asyncio
    async def test_only_yaml_when_role_reaction_disabled(self, cog):
        cog.role_reaction_manager = MagicMock()
        cog.role_reaction_manager.get_message_info = AsyncMock(return_value=(1, 999))
        guild = MagicMock(spec=discord.Guild)
        guild.id = 42
        with patch(
            "cogs.top_reactions.get_settings",
            return_value=self._settings_with(
                ignored_message_ids=[100, 200],
                ignore_role_reaction=False,
            ),
        ):
            result = await cog._build_excluded_message_ids(guild)
        assert result == {100, 200}
        cog.role_reaction_manager.get_message_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_combines_yaml_and_role_reaction_message(self, cog):
        cog.role_reaction_manager = MagicMock()
        cog.role_reaction_manager.get_message_info = AsyncMock(return_value=(1, 999))
        guild = MagicMock(spec=discord.Guild)
        guild.id = 42
        with patch(
            "cogs.top_reactions.get_settings",
            return_value=self._settings_with(
                ignored_message_ids=[100],
                ignore_role_reaction=True,
            ),
        ):
            result = await cog._build_excluded_message_ids(guild)
        assert result == {100, 999}

    @pytest.mark.asyncio
    async def test_role_reaction_message_not_set_is_safe(self, cog):
        cog.role_reaction_manager = MagicMock()
        cog.role_reaction_manager.get_message_info = AsyncMock(return_value=None)
        guild = MagicMock(spec=discord.Guild)
        guild.id = 42
        with patch(
            "cogs.top_reactions.get_settings",
            return_value=self._settings_with(
                ignored_message_ids=[],
                ignore_role_reaction=True,
            ),
        ):
            result = await cog._build_excluded_message_ids(guild)
        assert result == set()

    @pytest.mark.asyncio
    async def test_role_reaction_lookup_error_does_not_crash(self, cog):
        cog.role_reaction_manager = MagicMock()
        cog.role_reaction_manager.get_message_info = AsyncMock(side_effect=Exception("db down"))
        guild = MagicMock(spec=discord.Guild)
        guild.id = 42
        with patch(
            "cogs.top_reactions.get_settings",
            return_value=self._settings_with(
                ignored_message_ids=[42],
                ignore_role_reaction=True,
            ),
        ):
            result = await cog._build_excluded_message_ids(guild)
        # Только yaml-список — ошибка при чтении role-реакций не валит выдачу.
        assert result == {42}

    @pytest.mark.asyncio
    async def test_no_guild_means_no_role_reaction_lookup(self, cog):
        cog.role_reaction_manager = MagicMock()
        cog.role_reaction_manager.get_message_info = AsyncMock(return_value=(1, 999))
        with patch(
            "cogs.top_reactions.get_settings",
            return_value=self._settings_with(
                ignored_message_ids=[7],
                ignore_role_reaction=True,
            ),
        ):
            result = await cog._build_excluded_message_ids(None)
        assert result == {7}
        cog.role_reaction_manager.get_message_info.assert_not_called()


class TestPaginationView:
    """Тесты пагинации."""

    def _make_entries(self, n: int) -> list[LeaderboardEntry]:
        return [
            LeaderboardEntry(
                message_id=i,
                channel_id=1,
                author_id=1,
                content=f"msg {i}",
                jump_url=f"https://x/{i}",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reactor_count=n - i,
                is_historical=False,
            )
            for i in range(n)
        ]

    @pytest.mark.asyncio
    async def test_total_pages_calculation(self):
        entries = self._make_entries(50)
        view = TopReactionsView(
            entries=entries,
            period="all",
            per_page=10,
            guild=None,
            invoker_id=1,
            timeout=60,
        )
        assert view.total_pages == 5

    @pytest.mark.asyncio
    async def test_page_entries_first_page(self):
        entries = self._make_entries(25)
        view = TopReactionsView(
            entries=entries,
            period="all",
            per_page=10,
            guild=None,
            invoker_id=1,
            timeout=60,
        )
        page = view._page_entries()
        assert len(page) == 10
        assert page[0].message_id == 0

    @pytest.mark.asyncio
    async def test_page_entries_last_page(self):
        entries = self._make_entries(25)
        view = TopReactionsView(
            entries=entries,
            period="all",
            per_page=10,
            guild=None,
            invoker_id=1,
            timeout=60,
        )
        view.current_page = 2
        page = view._page_entries()
        assert len(page) == 5  # остаток

    @pytest.mark.asyncio
    async def test_interaction_check_blocks_other_users(self):
        entries = self._make_entries(5)
        view = TopReactionsView(
            entries=entries,
            period="all",
            per_page=10,
            guild=None,
            invoker_id=42,
            timeout=60,
        )
        interaction = MagicMock()
        interaction.user.id = 999
        interaction.response.send_message = AsyncMock()
        result = await view.interaction_check(interaction)
        assert result is False
        interaction.response.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_interaction_check_allows_invoker(self):
        entries = self._make_entries(5)
        view = TopReactionsView(
            entries=entries,
            period="all",
            per_page=10,
            guild=None,
            invoker_id=42,
            timeout=60,
        )
        interaction = MagicMock()
        interaction.user.id = 42
        result = await view.interaction_check(interaction)
        assert result is True


class TestPeriodLabel:
    """Юнит-тесты на _period_label — заголовок embed зависит от выбранного периода."""

    def test_explicit_year_and_month(self):
        assert _period_label("month", year=2024, month=3) == "март 2024"

    def test_explicit_year_only(self):
        assert _period_label("month", year=2024) == "2024"

    def test_explicit_month_only(self):
        assert _period_label("month", month=11) == "ноябрь"

    def test_period_month_no_args(self):
        assert _period_label("month") == "месяц"

    def test_period_year_no_args(self):
        assert _period_label("year") == "год"

    def test_period_all_no_args(self):
        assert _period_label("all") == "всё время"


class TestAuthorsEmbed:
    """Юнит-тесты на _build_authors_embed."""

    def _make_authors(self, n: int) -> list[AuthorLeaderboardEntry]:
        return [
            AuthorLeaderboardEntry(
                author_id=100 + i,
                total_reactions=(n - i) * 5,
                message_count=n - i,
            )
            for i in range(n)
        ]

    def test_empty_entries_show_placeholder(self):
        embed = _build_authors_embed(
            entries=[],
            page=0,
            total_pages=1,
            period="month",
            guild=None,
        )
        assert embed.description is not None
        assert "Пока нет авторов" in embed.description

    def test_lists_authors_with_counts(self):
        entries = self._make_authors(3)
        embed = _build_authors_embed(
            entries=entries,
            page=0,
            total_pages=1,
            period="month",
            guild=None,
        )
        # Сумма реакций и число сообщений должны быть в выдаче
        assert embed.description is not None
        assert "15" in embed.description  # первый автор: 3*5
        assert "3 сообщ." in embed.description

    def test_title_uses_period_label(self):
        embed = _build_authors_embed(
            entries=self._make_authors(1),
            page=0,
            total_pages=1,
            period="month",
            guild=None,
            year=2024,
            month=2,
        )
        assert "Топ авторов" in embed.title
        assert "февраль 2024" in embed.title

    def test_pagination_footer_shown_when_multiple_pages(self):
        embed = _build_authors_embed(
            entries=self._make_authors(2),
            page=0,
            total_pages=3,
            period="month",
            guild=None,
        )
        assert embed.footer.text == "Страница 1 из 3"


class TestPaginationViewWithAuthors:
    """View должен корректно рендерить и embed авторов, и embed сообщений."""

    @pytest.mark.asyncio
    async def test_renders_authors_embed_when_entries_are_authors(self):
        entries = [
            AuthorLeaderboardEntry(author_id=100, total_reactions=10, message_count=2)
        ]
        view = TopReactionsView(
            entries=entries,
            period="month",
            per_page=10,
            guild=None,
            invoker_id=1,
            timeout=60,
        )
        embed = view.render_embed()
        assert "Топ авторов" in embed.title

    @pytest.mark.asyncio
    async def test_renders_messages_embed_when_entries_are_messages(self):
        entries = [
            LeaderboardEntry(
                message_id=1,
                channel_id=1,
                author_id=1,
                content="hi",
                jump_url="https://x/1",
                posted_at=datetime(2024, 1, 1, tzinfo=UTC),
                reactor_count=3,
                is_historical=False,
            )
        ]
        view = TopReactionsView(
            entries=entries,
            period="month",
            per_page=10,
            guild=None,
            invoker_id=1,
            timeout=60,
        )
        embed = view.render_embed()
        assert "Топ сообщений" in embed.title


class TestMonthlyReportTask:
    """Тесты автоматической ежемесячной задачи."""

    @pytest.mark.asyncio
    async def test_skips_when_not_first_day_of_month(self, cog):
        """tasks.loop с time= триггерится каждый день — мы фильтруем по 1-му числу."""
        with patch("cogs.top_reactions.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 5, 15, 12, 0, tzinfo=UTC)
            cog._send_monthly_top_messages_report = AsyncMock()
            await cog.monthly_report()
        cog._send_monthly_top_messages_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_runs_for_previous_month_on_first_day(self, cog):
        with patch("cogs.top_reactions.datetime") as mock_dt:
            # МСК — 1 июня 2024
            mock_dt.now.return_value = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
            cog._send_monthly_top_messages_report = AsyncMock()
            await cog.monthly_report()
        cog._send_monthly_top_messages_report.assert_awaited_once_with(2024, 5)

    @pytest.mark.asyncio
    async def test_january_first_wraps_to_previous_year_december(self, cog):
        with patch("cogs.top_reactions.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
            cog._send_monthly_top_messages_report = AsyncMock()
            await cog.monthly_report()
        cog._send_monthly_top_messages_report.assert_awaited_once_with(2024, 12)


class TestSendMonthlyReport:
    """Юнит-тесты на _send_monthly_top_messages_report."""

    @pytest.mark.asyncio
    async def test_returns_false_when_channel_not_found(self, cog):
        cog.bot.get_channel = MagicMock(return_value=None)
        cog.bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), "x"))
        result = await cog._send_monthly_top_messages_report(2024, 5)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_entries(self, cog):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = MagicMock(spec=discord.Guild)
        channel.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=channel)
        cog._build_excluded_message_ids = AsyncMock(return_value=set())
        cog.manager.get_leaderboard = AsyncMock(return_value=[])

        result = await cog._send_monthly_top_messages_report(2024, 5)
        assert result is False
        channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_embed_when_entries_found(self, cog):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = MagicMock(spec=discord.Guild)
        channel.guild.get_member = MagicMock(return_value=None)
        channel.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=channel)
        cog._build_excluded_message_ids = AsyncMock(return_value=set())
        cog.manager.get_leaderboard = AsyncMock(
            return_value=[
                LeaderboardEntry(
                    message_id=1,
                    channel_id=1,
                    author_id=10,
                    content="hi",
                    jump_url="https://x/1",
                    posted_at=datetime(2024, 5, 10, tzinfo=UTC),
                    reactor_count=4,
                    is_historical=False,
                )
            ]
        )

        result = await cog._send_monthly_top_messages_report(2024, 5)
        assert result is True
        channel.send.assert_awaited_once()
        # Проверяем, что вызвано с правильным каналом и embed
        call = channel.send.await_args
        assert "май 2024" in call.kwargs["content"]
        assert call.kwargs["embed"] is not None

    @pytest.mark.asyncio
    async def test_passes_year_month_to_data_manager(self, cog):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = MagicMock(spec=discord.Guild)
        channel.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=channel)
        cog._build_excluded_message_ids = AsyncMock(return_value={42})
        cog.manager.get_leaderboard = AsyncMock(return_value=[])

        await cog._send_monthly_top_messages_report(2023, 11)
        cog.manager.get_leaderboard.assert_awaited_once()
        kwargs = cog.manager.get_leaderboard.await_args.kwargs
        assert kwargs["period"] == "month"
        assert kwargs["year"] == 2023
        assert kwargs["month"] == 11
        assert kwargs["excluded_message_ids"] == {42}
