"""Тесты для CsLinksCog — команды привязки аккаунтов FACEIT (CS2)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.cs_links import CsLinksCog


def _make_link(player_id: str, nickname: str) -> MagicMock:
    """Создаёт мок-объект CsLink."""
    link = MagicMock()
    link.faceit_player_id = player_id
    link.nickname = nickname
    return link


def _make_settings() -> MagicMock:
    """Мок настроек с заданным FACEIT-ключом и лимитом привязок."""
    settings = MagicMock()
    settings.faceit_api_key = "key"
    settings.limits.links_max_per_user = 5
    return settings


@pytest.fixture
def mock_links_manager():
    """Создаёт мок менеджера CS-привязок."""
    manager = MagicMock()
    manager.get_links = AsyncMock()
    manager.add_link = AsyncMock()
    manager.remove_link = AsyncMock()
    manager.remove_all_links = AsyncMock()
    return manager


@pytest.fixture
def cs_links_cog(mock_bot, mock_links_manager):
    """Создаёт экземпляр CsLinksCog с мок-зависимостями."""
    cog = CsLinksCog(mock_bot)
    cog.links_manager = mock_links_manager
    return cog


class TestInit:
    """Тесты инициализации и регистрации команд."""

    def test_init(self, mock_bot):
        cog = CsLinksCog(mock_bot)
        assert isinstance(cog, CsLinksCog)
        assert cog.bot == mock_bot

    def test_registers_commands(self, cs_links_cog):
        names = {cmd.name for cmd in cs_links_cog.get_commands()}
        assert names == {"cslink", "csunlink", "cslinks"}


class TestCsLink:
    """Тесты команды cslink."""

    @pytest.mark.asyncio
    async def test_success(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = []
        mock_links_manager.add_link.return_value = True

        with (
            patch("cogs.cs_links.get_settings", return_value=_make_settings()),
            patch(
                "cogs.cs_links.resolve_player_by_nickname", new_callable=AsyncMock
            ) as mock_resolve,
            patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send,
        ):
            mock_resolve.return_value = {"player_id": "p1", "nickname": "Coolguy"}
            await cs_links_cog.cslink.callback(cs_links_cog, mock_context, "Coolguy")

        mock_links_manager.add_link.assert_awaited_once_with(1, "p1", "Coolguy")
        assert "успешно привязан" in mock_send.call_args[0][1]

    @pytest.mark.asyncio
    async def test_not_found(self, cs_links_cog, mock_context):
        mock_context.interaction = None

        with (
            patch("cogs.cs_links.get_settings", return_value=_make_settings()),
            patch(
                "cogs.cs_links.resolve_player_by_nickname", new_callable=AsyncMock
            ) as mock_resolve,
            patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send,
        ):
            mock_resolve.return_value = None
            await cs_links_cog.cslink.callback(cs_links_cog, mock_context, "Nope")

        assert "не найден" in mock_send.call_args[0][1]

    @pytest.mark.asyncio
    async def test_already_linked(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [_make_link("p1", "Coolguy")]

        with (
            patch("cogs.cs_links.get_settings", return_value=_make_settings()),
            patch(
                "cogs.cs_links.resolve_player_by_nickname", new_callable=AsyncMock
            ) as mock_resolve,
            patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send,
        ):
            mock_resolve.return_value = {"player_id": "p1", "nickname": "Coolguy"}
            await cs_links_cog.cslink.callback(cs_links_cog, mock_context, "Coolguy")

        assert "уже привязан" in mock_send.call_args[0][1]
        mock_links_manager.add_link.assert_not_called()

    @pytest.mark.asyncio
    async def test_limit_reached(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [_make_link(f"p{i}", f"n{i}") for i in range(5)]

        with (
            patch("cogs.cs_links.get_settings", return_value=_make_settings()),
            patch(
                "cogs.cs_links.resolve_player_by_nickname", new_callable=AsyncMock
            ) as mock_resolve,
            patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send,
        ):
            mock_resolve.return_value = {"player_id": "new", "nickname": "New"}
            await cs_links_cog.cslink.callback(cs_links_cog, mock_context, "New")

        assert "лимита" in mock_send.call_args[0][1]
        mock_links_manager.add_link.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_api_key(self, cs_links_cog, mock_context):
        mock_context.interaction = None
        settings = _make_settings()
        settings.faceit_api_key = None

        with (
            patch("cogs.cs_links.get_settings", return_value=settings),
            patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send,
        ):
            await cs_links_cog.cslink.callback(cs_links_cog, mock_context, "Coolguy")

        assert "FACEIT_API_KEY" in mock_send.call_args[0][1]


class TestCsUnlink:
    """Тесты команды csunlink."""

    @pytest.mark.asyncio
    async def test_no_links(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = []

        with patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send:
            await cs_links_cog.csunlink.callback(cs_links_cog, mock_context)

        assert "нет привязанных" in mock_send.call_args[0][1]

    @pytest.mark.asyncio
    async def test_specific_with_remaining(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [
            _make_link("p1", "Coolguy"),
            _make_link("p2", "Other"),
        ]
        mock_links_manager.remove_link.return_value = True

        with patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send:
            await cs_links_cog.csunlink.callback(cs_links_cog, mock_context, "Coolguy")

        mock_links_manager.remove_link.assert_awaited_once_with(1, "p1")
        message = mock_send.call_args[0][1]
        assert "отвязан" in message
        assert "Other" in message

    @pytest.mark.asyncio
    async def test_specific_not_found(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [_make_link("p1", "Coolguy")]

        with patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send:
            await cs_links_cog.csunlink.callback(cs_links_cog, mock_context, "Unknown")

        assert "не привязан" in mock_send.call_args[0][1]
        mock_links_manager.remove_link.assert_not_called()

    @pytest.mark.asyncio
    async def test_all(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [_make_link("p1", "Coolguy")]
        mock_links_manager.remove_all_links.return_value = 1

        with patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send:
            await cs_links_cog.csunlink.callback(cs_links_cog, mock_context)

        mock_links_manager.remove_all_links.assert_awaited_once_with(1)
        assert "отвязаны" in mock_send.call_args[0][1]


class TestCsLinks:
    """Тесты команды cslinks."""

    @pytest.mark.asyncio
    async def test_single(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [_make_link("p1", "Coolguy")]

        with patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send:
            await cs_links_cog.cslinks.callback(cs_links_cog, mock_context)

        message = mock_send.call_args[0][1]
        assert "Ваш привязанный аккаунт FACEIT" in message
        assert "Coolguy" in message

    @pytest.mark.asyncio
    async def test_multiple(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [
            _make_link("p1", "Coolguy"),
            _make_link("p2", "Other"),
        ]

        with patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send:
            await cs_links_cog.cslinks.callback(cs_links_cog, mock_context)

        message = mock_send.call_args[0][1]
        assert "Coolguy" in message
        assert "Other" in message

    @pytest.mark.asyncio
    async def test_none(self, cs_links_cog, mock_context, mock_links_manager):
        mock_context.author.id = 1
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = []

        with patch.object(cs_links_cog, "send_response", new_callable=AsyncMock) as mock_send:
            await cs_links_cog.cslinks.callback(cs_links_cog, mock_context)

        assert "cslink" in mock_send.call_args[0][1]


class TestCsunlinkAutocomplete:
    """Тесты автокомплита /csunlink."""

    @pytest.mark.asyncio
    async def test_lists_linked_nicknames(self, cs_links_cog, mock_links_manager):
        """Без ввода отдаёт ники всех привязанных аккаунтов."""
        mock_links_manager.get_links.return_value = [
            _make_link("p1", "Coolguy"),
            _make_link("p2", "Other"),
        ]
        interaction = MagicMock()
        interaction.user = MagicMock(id=1)

        choices = await cs_links_cog.csunlink_autocomplete(interaction, "")

        mock_links_manager.get_links.assert_awaited_once_with(1)
        assert [c.value for c in choices] == ["Coolguy", "Other"]

    @pytest.mark.asyncio
    async def test_filters_case_insensitive(self, cs_links_cog, mock_links_manager):
        """Ввод сужает выдачу без учёта регистра."""
        mock_links_manager.get_links.return_value = [
            _make_link("p1", "Coolguy"),
            _make_link("p2", "Other"),
        ]
        interaction = MagicMock()
        interaction.user = MagicMock(id=1)

        choices = await cs_links_cog.csunlink_autocomplete(interaction, "cool")

        assert [c.value for c in choices] == ["Coolguy"]

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, cs_links_cog, mock_links_manager):
        """Ошибка менеджера приводит к пустому списку, а не к исключению."""
        mock_links_manager.get_links.side_effect = RuntimeError("db down")
        interaction = MagicMock()
        interaction.user = MagicMock(id=1)

        assert await cs_links_cog.csunlink_autocomplete(interaction, "") == []


class TestLifecycle:
    """Тесты жизненного цикла кога."""

    @pytest.mark.asyncio
    async def test_cog_unload(self, cs_links_cog):
        await cs_links_cog.cog_unload()

    @pytest.mark.asyncio
    async def test_setup(self, mock_bot):
        from cogs.cs_links import setup

        mock_bot.add_cog = AsyncMock()
        await setup(mock_bot)
        added = mock_bot.add_cog.call_args[0][0]
        assert isinstance(added, CsLinksCog)
