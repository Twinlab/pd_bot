"""Тесты для TopReactionsCog — листенеры реакций и команда /topreactions."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.top_reactions import TopReactionsCog, TopReactionsView, _build_embed
from utils.top_reactions_data_manager import LeaderboardEntry


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
